"""Visual button locator for FIND_AND_CLICK action_type.

When a banking-app banner pushes UI elements around, a recorded fixed
coordinate misses. This module locates the button by template matching
and / or OCR within an ROI, then converts the pixel hit back to arm
coordinates and clicks.

Stays adjacent to existing modules (camera, calibration, screen_checker
reference path, ocr). No worker / action_type changes elsewhere are
required beyond actions.execute_find_and_click + ENUM.

Public API:
    locate_button(rotated, template_bgr, ocr_text, combine, threshold,
                  roi_pct, verify_radius_px, disambiguation,
                  ocr_match, ocr_case_sensitive) -> dict | None
    find_and_click(config, station_id, bank_code, arm_name, arm, cam,
                   executor, anchor_pos, click_after_find=True) -> dict
"""
import asyncio
import logging
import os
import re

import cv2
import numpy as np

from app import calibration, database, ocr, screen_checker

logger = logging.getLogger(__name__)


DEFAULT_THRESHOLD = 0.8
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY_MS = 800
DEFAULT_VERIFY_RADIUS_PX = 30
DEFAULT_OFFSETS_MM = [(0, 0), (-2, 0), (0, -2)]


# === Template path (independent from CHECK_SCREEN's reference) ===========
# Stores under references/<arm>/<bank>/<name>_tpl.jpg (or legacy without arm).

def get_template_path(bank_code: str, name: str, arm_name: str = None):
    base_dir = os.path.dirname(screen_checker.get_reference_path(bank_code, "_x", arm_name))
    return os.path.join(base_dir, "%s_tpl.jpg" % name)


def load_template(bank_code: str, name: str, arm_name: str = None):
    path = get_template_path(bank_code, name, arm_name)
    if not os.path.exists(path):
        # legacy fallback (no arm subdir)
        path = get_template_path(bank_code, name)
    if not os.path.exists(path):
        logger.error("FIND_AND_CLICK: template '%s' not found at %s", name, path)
        return None
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        logger.error("FIND_AND_CLICK: template decode failed: %s", path)
    return img


# === ROI helpers =========================================================

def _roi_pixels_from_percent(rotated_shape, roi_pct):
    """Convert percentage ROI to pixel rect (x1, y1, x2, y2) in the rotated frame."""
    h, w = rotated_shape[:2]
    if not roi_pct:
        return 0, 0, w, h
    x1 = max(0, int(w * roi_pct.get("left_percent", 0) / 100.0))
    y1 = max(0, int(h * roi_pct.get("top_percent", 0) / 100.0))
    x2 = min(w, int(w * roi_pct.get("right_percent", 100) / 100.0))
    y2 = min(h, int(h * roi_pct.get("bottom_percent", 100) / 100.0))
    if x2 <= x1 or y2 <= y1:
        return 0, 0, w, h
    return x1, y1, x2, y2


# === Template matching ===================================================

def _template_candidates(roi_bgr, template_bgr, threshold):
    """Run cv2.matchTemplate and return (candidates, best_score, error).

    candidates: list of dicts {score, cx, cy, w, h} above threshold (NMS applied).
    best_score: max raw score across the score map regardless of threshold —
        useful for diagnostics ("template best was 0.62 but threshold is 0.80").
    error: string code if template/ROI sizing is wrong, else None.
    """
    rh, rw = roi_bgr.shape[:2]
    th, tw = template_bgr.shape[:2]
    if th > rh or tw > rw:
        logger.warning("FIND_AND_CLICK: template %dx%d larger than ROI %dx%d", tw, th, rw, rh)
        return [], 0.0, "template_larger_than_roi"

    # Use grayscale for speed and lighting tolerance.
    roi_g = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    tpl_g = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(roi_g, tpl_g, cv2.TM_CCOEFF_NORMED)
    _, global_max, _, _ = cv2.minMaxLoc(res)

    candidates = []
    res_copy = res.copy()
    min_dx = max(1, tw // 2)
    min_dy = max(1, th // 2)
    while True:
        _, max_val, _, max_loc = cv2.minMaxLoc(res_copy)
        if max_val < threshold:
            break
        x0, y0 = max_loc
        candidates.append({
            "score": float(max_val),
            "cx": x0 + tw // 2,
            "cy": y0 + th // 2,
            "w": tw,
            "h": th,
        })
        # Suppress this peak so the next loop finds a different region.
        x1 = max(0, x0 - min_dx)
        y1 = max(0, y0 - min_dy)
        x2 = min(res_copy.shape[1], x0 + min_dx + 1)
        y2 = min(res_copy.shape[0], y0 + min_dy + 1)
        res_copy[y1:y2, x1:x2] = -1.0
        if len(candidates) >= 16:  # safety bound
            break
    return candidates, float(global_max), None


def _pick_candidate(candidates, mode, roi_shape):
    """Apply disambiguation strategy. Returns one candidate or None."""
    if not candidates:
        return None
    if mode == "unique_only":
        return candidates[0] if len(candidates) == 1 else None
    if mode == "closest_to_center":
        rh, rw = roi_shape[:2]
        rcx, rcy = rw / 2.0, rh / 2.0
        return min(candidates, key=lambda c: (c["cx"] - rcx) ** 2 + (c["cy"] - rcy) ** 2)
    # default: best_score
    return max(candidates, key=lambda c: c["score"])


# === OCR helpers =========================================================

def _ocr_text_match(haystack: str, needle: str, mode: str, case_sensitive: bool) -> bool:
    if not haystack or not needle:
        return False
    if not case_sensitive:
        haystack = haystack.lower()
        needle = needle.lower()
    if mode == "exact":
        return haystack.strip() == needle.strip()
    if mode == "regex":
        try:
            return re.search(needle, haystack) is not None
        except re.error:
            return False
    # default: contains
    return needle in haystack


def _ocr_in_region(crop_bgr) -> str:
    """Run OCR on a cropped BGR image. Returns concatenated text."""
    reader = ocr.get_reader()
    if reader is None:
        return ""
    if reader == "tesseract":
        import pytesseract
        return pytesseract.image_to_string(crop_bgr)
    results = reader.readtext(crop_bgr, detail=0)
    return " ".join(results)


def _ocr_locate(roi_bgr, needle: str, match: str, case_sensitive: bool):
    """Run EasyOCR/Tesseract on the entire ROI, return list of bbox-center
    candidates whose text matches the needle. Each candidate has the same
    shape as a template candidate so disambiguation works uniformly."""
    reader = ocr.get_reader()
    if reader is None:
        return []
    if reader == "tesseract":
        # Tesseract path doesn't easily yield per-word boxes here; return ROI center
        # if the whole-block OCR contains the needle.
        text = _ocr_in_region(roi_bgr)
        if _ocr_text_match(text, needle, match, case_sensitive):
            rh, rw = roi_bgr.shape[:2]
            return [{"score": 1.0, "cx": rw // 2, "cy": rh // 2, "w": rw, "h": rh, "text": text}]
        return []
    results = reader.readtext(roi_bgr, detail=1)
    out = []
    for entry in results:
        bbox, text, conf = entry[0], entry[1], entry[2] if len(entry) > 2 else 1.0
        if not _ocr_text_match(text, needle, match, case_sensitive):
            continue
        xs = [int(p[0]) for p in bbox]
        ys = [int(p[1]) for p in bbox]
        cx = (min(xs) + max(xs)) // 2
        cy = (min(ys) + max(ys)) // 2
        out.append({
            "score": float(conf),
            "cx": cx,
            "cy": cy,
            "w": max(xs) - min(xs),
            "h": max(ys) - min(ys),
            "text": text,
        })
    return out


def _ocr_verify_around(roi_bgr, cx, cy, radius, needle, match, case_sensitive):
    """Crop a square around (cx, cy) inside roi_bgr and check text via OCR."""
    rh, rw = roi_bgr.shape[:2]
    x1 = max(0, cx - radius)
    y1 = max(0, cy - radius)
    x2 = min(rw, cx + radius)
    y2 = min(rh, cy + radius)
    if x2 <= x1 or y2 <= y1:
        return False, ""
    crop = roi_bgr[y1:y2, x1:x2]
    text = _ocr_in_region(crop)
    return _ocr_text_match(text, needle, match, case_sensitive), text


# === Main locator ========================================================

def locate_button(rotated, *, template_bgr, ocr_text, combine, threshold,
                  roi_pct, verify_radius_px, disambiguation,
                  ocr_match, ocr_case_sensitive):
    """Locate a button inside the rotated frame. Returns a dict whose 'found'
    key indicates success. Always populated with diagnostic fields so callers
    (and operators reading the log) can see exactly why a match did not stick.

    On success:
        {found: True, rotated_px, rotated_py, score, method, candidates, ...}

    On failure:
        {found: False, reason: <code>, method, roi_rect, ...metrics}

    Failure reasons (codes):
        roi_empty                  ROI percentages produced a degenerate rect
        template_disabled          combine asked for template but it was off
        ocr_disabled               combine asked for OCR but it was off
        template_larger_than_roi   template image is bigger than the ROI crop
        template_below_threshold   best matchTemplate score < threshold
        ocr_no_match               OCR did not see the requested text in ROI
        ocr_verify_failed          template found candidates but OCR rejected each
        disambiguation_rejected    candidates exist but disambiguation strategy returned none
        unknown_combine            bad config value
    """
    x1, y1, x2, y2 = _roi_pixels_from_percent(rotated.shape, roi_pct)
    roi = rotated[y1:y2, x1:x2]
    base = {
        "method": combine,
        "roi_rect": [int(x1), int(y1), int(x2), int(y2)],
        "threshold": threshold,
    }
    if roi.size == 0:
        return {"found": False, "reason": "roi_empty", **base}

    candidates = []

    if combine == "template_only":
        if template_bgr is None:
            return {"found": False, "reason": "template_disabled", **base}
        cands, best_score, err = _template_candidates(roi, template_bgr, threshold)
        base["best_template_score"] = round(best_score, 4)
        base["template_candidates"] = len(cands)
        if err:
            return {"found": False, "reason": err, **base}
        if not cands:
            return {"found": False, "reason": "template_below_threshold", **base}
        candidates = cands

    elif combine == "ocr_only":
        if not ocr_text:
            return {"found": False, "reason": "ocr_disabled", **base}
        cands = _ocr_locate(roi, ocr_text, ocr_match, ocr_case_sensitive)
        base["ocr_candidates"] = len(cands)
        if not cands:
            return {"found": False, "reason": "ocr_no_match", **base}
        candidates = cands

    elif combine == "template_then_ocr":
        if template_bgr is None:
            return {"found": False, "reason": "template_disabled", **base}
        if not ocr_text:
            return {"found": False, "reason": "ocr_disabled", **base}
        tpl_cands, best_score, err = _template_candidates(roi, template_bgr, threshold)
        base["best_template_score"] = round(best_score, 4)
        base["template_candidates"] = len(tpl_cands)
        if err:
            return {"found": False, "reason": err, **base}
        if not tpl_cands:
            return {"found": False, "reason": "template_below_threshold", **base}
        # Try OCR verify on each candidate by descending template score.
        # Capture per-candidate OCR text for the log so operators can tell
        # whether OCR saw something close to the target word but not matching.
        verified = []
        ocr_attempts = []
        for c in sorted(tpl_cands, key=lambda x: -x["score"]):
            ok, txt = _ocr_verify_around(
                roi, c["cx"], c["cy"], verify_radius_px,
                ocr_text, ocr_match, ocr_case_sensitive)
            ocr_attempts.append({
                "tpl_score": round(c["score"], 4),
                "ocr_pass": bool(ok),
                "ocr_text": (txt or "")[:60],
            })
            if ok:
                c2 = dict(c)
                c2["text"] = txt
                verified.append(c2)
        base["ocr_attempts"] = ocr_attempts[:5]  # cap log size
        base["ocr_verified"] = len(verified)
        base["ocr_target"] = ocr_text
        if not verified:
            return {"found": False, "reason": "ocr_verify_failed", **base}
        candidates = verified

    else:
        return {"found": False, "reason": "unknown_combine", **base}

    pick = _pick_candidate(candidates, disambiguation, roi.shape)
    if pick is None:
        return {
            "found": False,
            "reason": "disambiguation_rejected",
            "candidates": len(candidates),
            "disambiguation": disambiguation,
            **base,
        }

    return {
        "found": True,
        "rotated_px": int(x1 + pick["cx"]),
        "rotated_py": int(y1 + pick["cy"]),
        "score": pick["score"],
        "candidates": len(candidates),
        "ocr_text": pick.get("text"),
        **base,
    }


# === Hardware glue =======================================================

async def _hw(executor, func, *args):
    if executor is None:
        return func(*args)
    return await asyncio.get_event_loop().run_in_executor(executor, func, *args)


async def _get_arm_limits(arm_id):
    """Fetch (max_x, max_y) for the arm hosting this station. Falls back
    to schema defaults if arm row missing or column NULL."""
    row = await database.fetchone(
        "SELECT max_x, max_y FROM arms WHERE id = %s", (arm_id,))
    if not row:
        return 90.0, 120.0
    return float(row["max_x"] or 90.0), float(row["max_y"] or 120.0)


async def _get_arm_id_for_station(station_id):
    row = await database.fetchone(
        "SELECT arm_id FROM stations WHERE id = %s", (station_id,))
    return int(row["arm_id"]) if row else None


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# === Public orchestrator =================================================

async def find_and_click(*, config, station_id, bank_code, arm_name,
                         arm, cam, executor, anchor_pos,
                         click_after_find=True):
    """Move camera through configured offsets, locate button, click it.

    Args:
        config: parsed description JSON (see plan section three).
        anchor_pos: (cam_x, cam_y) recorded camera position for this step.
        click_after_find: True for production execution; Builder may pass
            False to preview without committing the click.

    Returns diagnostics dict. Raises RuntimeError on final failure.
    """
    # --- read config with defaults ---------------------------------------
    template_cfg = config.get("template") or {}
    ocr_cfg = config.get("ocr") or {}
    tpl_enabled = bool(template_cfg.get("enabled"))
    ocr_enabled = bool(ocr_cfg.get("enabled"))
    # Enabled checkboxes are the source of truth. An explicit `combine` in
    # the config is only honored when both providers are enabled (the only
    # case where the user actually has a choice between template_only /
    # ocr_only / template_then_ocr). This prevents the failure where a user
    # unchecks Template but combine still says "template_then_ocr" from a
    # previous setting.
    if tpl_enabled and ocr_enabled:
        combine = config.get("combine") or "template_then_ocr"
    elif tpl_enabled:
        combine = "template_only"
    elif ocr_enabled:
        combine = "ocr_only"
    else:
        raise RuntimeError(
            "FIND_AND_CLICK: both template and OCR disabled — nothing to match")
    threshold = float(config.get("threshold") or DEFAULT_THRESHOLD)
    max_retries = int(config.get("max_retries") or DEFAULT_MAX_RETRIES)
    retry_delay_ms = int(config.get("retry_delay_ms") or DEFAULT_RETRY_DELAY_MS)
    verify_radius_px = int(config.get("verify_radius_px") or DEFAULT_VERIFY_RADIUS_PX)
    disambiguation = config.get("disambiguation") or "best_score"
    roi_pct = config.get("roi") or None
    offsets = [tuple(o) for o in (config.get("camera_offsets_mm") or DEFAULT_OFFSETS_MM)]
    if not offsets:
        offsets = list(DEFAULT_OFFSETS_MM)
    # cap retries to offsets available
    offsets = offsets[:max(1, max_retries)] if len(offsets) >= max_retries else offsets

    ocr_match = (ocr_cfg.get("match") or "contains").lower()
    ocr_case_sensitive = bool(ocr_cfg.get("case_sensitive"))
    ocr_text = ocr_cfg.get("text") if ocr_cfg.get("enabled") else None

    # --- load template if needed ----------------------------------------
    template_bgr = None
    if template_cfg.get("enabled"):
        tpl_name = template_cfg.get("name")
        if not tpl_name:
            raise RuntimeError("FIND_AND_CLICK: template enabled but name missing")
        template_bgr = load_template(bank_code, tpl_name, arm_name=arm_name)
        if template_bgr is None:
            raise RuntimeError("FIND_AND_CLICK: template '%s' not found" % tpl_name)

    if combine in ("ocr_only", "template_then_ocr") and not ocr_text:
        raise RuntimeError("FIND_AND_CLICK: combine=%s but ocr.text missing" % combine)

    # --- arm safety bounds (guard camera offsets) -----------------------
    arm_id = await _get_arm_id_for_station(station_id)
    if arm_id is None:
        raise RuntimeError("FIND_AND_CLICK: station %d not found" % station_id)
    max_x, max_y = await _get_arm_limits(arm_id)

    cam_x0, cam_y0 = anchor_pos
    diagnostics_attempts = []

    for offset_idx, (dx, dy) in enumerate(offsets):
        cam_x = _clamp(cam_x0 + dx, 0.0, max_x)
        cam_y = _clamp(cam_y0 + dy, 0.0, max_y)

        await _hw(executor, arm.move, cam_x, cam_y)
        await asyncio.sleep(retry_delay_ms / 1000.0)

        frame = await _hw(executor, cam.capture_fresh)
        if frame is None:
            logger.warning("FIND_AND_CLICK: capture failed at (%.1f, %.1f)", cam_x, cam_y)
            diagnostics_attempts.append({
                "attempt": offset_idx + 1, "cam_pos": [cam_x, cam_y],
                "found": False, "reason": "capture_failed",
            })
            continue
        rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)

        loc = locate_button(
            rotated,
            template_bgr=template_bgr,
            ocr_text=ocr_text,
            combine=combine,
            threshold=threshold,
            roi_pct=roi_pct,
            verify_radius_px=verify_radius_px,
            disambiguation=disambiguation,
            ocr_match=ocr_match,
            ocr_case_sensitive=ocr_case_sensitive,
        )

        # Build per-attempt diagnostics. Always include reason / metrics so
        # an operator looking at the log can tell template_below_threshold
        # apart from ocr_verify_failed apart from ROI-too-narrow.
        attempt_diag = {
            "attempt": offset_idx + 1,
            "cam_pos": [cam_x, cam_y],
            "found": bool(loc.get("found")),
            "reason": loc.get("reason") if not loc.get("found") else "ok",
        }
        for key in ("score", "method", "candidates", "rotated_px", "rotated_py",
                    "best_template_score", "template_candidates",
                    "ocr_candidates", "ocr_verified", "ocr_attempts", "ocr_target"):
            if key in loc:
                attempt_diag[key] = loc[key]
        diagnostics_attempts.append(attempt_diag)

        # Compose a single human-readable log line per attempt.
        log_extras = []
        if "best_template_score" in loc:
            log_extras.append("tpl_best=%.3f" % loc["best_template_score"])
        if "template_candidates" in loc:
            log_extras.append("tpl_cands=%d" % loc["template_candidates"])
        if "ocr_verified" in loc:
            log_extras.append("ocr_verified=%d" % loc["ocr_verified"])
        if loc.get("found"):
            log_extras.append("score=%.3f" % loc["score"])
        if "ocr_attempts" in loc and loc["ocr_attempts"]:
            top = loc["ocr_attempts"][0]
            log_extras.append("top_ocr='%s'(pass=%s)" % (top["ocr_text"], top["ocr_pass"]))
        logger.info(
            "FIND_AND_CLICK: attempt %d/%d cam=(%.1f,%.1f) found=%s reason=%s%s",
            offset_idx + 1, len(offsets), cam_x, cam_y,
            attempt_diag["found"], attempt_diag["reason"],
            (" " + " ".join(log_extras)) if log_extras else "")

        if not loc.get("found"):
            continue

        arm_x, arm_y = await calibration.pixel_to_arm(
            station_id, loc["rotated_px"], loc["rotated_py"], cam_x, cam_y)

        result = {
            "found": True,
            "attempts": offset_idx + 1,
            "score": loc["score"],
            "method": loc["method"],
            "candidates": loc["candidates"],
            "rotated_px": loc["rotated_px"],
            "rotated_py": loc["rotated_py"],
            "arm_x": arm_x,
            "arm_y": arm_y,
            "ocr_text": loc.get("ocr_text"),
            "diagnostics": diagnostics_attempts,
        }

        if click_after_find:
            await _hw(executor, arm.click, arm_x, arm_y)
            result["clicked"] = True
        else:
            result["clicked"] = False

        return result

    # Build a richer error message that surfaces the most informative reason
    # from the most recent attempt (typically the one with all offsets tried).
    last = diagnostics_attempts[-1] if diagnostics_attempts else {}
    detail_bits = []
    if "best_template_score" in last:
        detail_bits.append("tpl_best=%.3f" % last["best_template_score"])
    if "template_candidates" in last:
        detail_bits.append("tpl_cands=%d" % last["template_candidates"])
    if "ocr_verified" in last:
        detail_bits.append("ocr_verified=%d" % last["ocr_verified"])
    detail = (" " + " ".join(detail_bits)) if detail_bits else ""
    raise RuntimeError(
        "FIND_AND_CLICK: not found after %d attempt(s) — reason=%s combine=%s threshold=%.2f%s"
        % (len(offsets), last.get("reason", "unknown"), combine, threshold, detail))
