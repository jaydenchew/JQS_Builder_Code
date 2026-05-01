"""Visual swipe locator for FIND_AND_SWIPE action_type.

Solves the same UI-drift problem as FIND_AND_CLICK, but for swipe gestures.
A recorded fixed (start, end) misses the slider when a banner pushes the UI
down. This module finds the slider handle visually, then preserves the
recorded (end - start) offset to compute a shifted end and swipes there.

Maximizes reuse of [app/find_and_click.py](app/find_and_click.py): we import
its `locate_button` + helpers verbatim and add only the orchestration that
swaps "click" for "swipe with offset".

Public API:
    find_and_swipe(config, station_id, bank_code, arm_name, arm, cam,
                   executor, recorded_swipe, swipe_after_find=True) -> dict
"""
import asyncio
import logging

import cv2

from app import calibration
from app.find_and_click import (
    locate_button,
    load_template,
    _hw,
    _get_arm_id_for_station,
    _get_arm_limits,
    _clamp,
    DEFAULT_THRESHOLD,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY_MS,
    DEFAULT_VERIFY_RADIUS_PX,
    DEFAULT_OFFSETS_MM,
)

logger = logging.getLogger(__name__)


# Tolerance for "swipe shrunk too much after clamping". If the shifted end
# would clamp to within 70% of the recorded swipe distance we still execute
# but flag a warning in diagnostics. Operators tuning the recording position
# closer to arm boundaries should watch for this.
SWIPE_SHRINK_WARN_RATIO = 0.7


async def find_and_swipe(*, config, station_id, bank_code, arm_name,
                         arm, cam, executor, recorded_swipe,
                         camera_anchor=None,
                         swipe_after_find=True):
    """Move camera to anchor, locate slider start handle, apply recorded
    (end - start) offset, swipe.

    Args:
        config: parsed description JSON. Same schema as FIND_AND_CLICK
            (template/ocr/combine/threshold/roi/camera_offsets_mm/...). May
            also contain `camera_anchor_mm: [x, y]` (preferred over the
            keyword arg below).
        recorded_swipe: (sx_rec, sy_rec, ex_rec, ey_rec) from swipe_actions.
            Used only as the offset baseline — runtime swipe coords come
            from the matched template position + (end_rec - start_rec).
        camera_anchor: (cam_x, cam_y) where the arm moves to capture the
            search frame. Falls back to config.camera_anchor_mm, then to
            recorded_swipe[:2] (the legacy "start = camera anchor" mode).
        swipe_after_find: True for production; Builder may pass False to
            preview where the slider was located without committing the swipe.

    Returns diagnostics dict on success. Raises RuntimeError on final failure
    so arm_worker takes the soft-error stall path (auto-runs per-arm STALL
    flow per DD-024).
    """
    # --- read config (same resolution rule as find_and_click) -----------
    template_cfg = config.get("template") or {}
    ocr_cfg = config.get("ocr") or {}
    tpl_enabled = bool(template_cfg.get("enabled"))
    ocr_enabled = bool(ocr_cfg.get("enabled"))
    if tpl_enabled and ocr_enabled:
        combine = config.get("combine") or "template_then_ocr"
    elif tpl_enabled:
        combine = "template_only"
    elif ocr_enabled:
        combine = "ocr_only"
    else:
        raise RuntimeError(
            "FIND_AND_SWIPE: both template and OCR disabled — nothing to match")

    threshold = float(config.get("threshold") or DEFAULT_THRESHOLD)
    max_retries = int(config.get("max_retries") or DEFAULT_MAX_RETRIES)
    retry_delay_ms = int(config.get("retry_delay_ms") or DEFAULT_RETRY_DELAY_MS)
    verify_radius_px = int(config.get("verify_radius_px") or DEFAULT_VERIFY_RADIUS_PX)
    disambiguation = config.get("disambiguation") or "best_score"
    roi_pct = config.get("roi") or None
    offsets = [tuple(o) for o in (config.get("camera_offsets_mm") or DEFAULT_OFFSETS_MM)]
    if not offsets:
        offsets = list(DEFAULT_OFFSETS_MM)
    offsets = offsets[:max(1, max_retries)] if len(offsets) >= max_retries else offsets

    ocr_match = (ocr_cfg.get("match") or "contains").lower()
    ocr_case_sensitive = bool(ocr_cfg.get("case_sensitive"))
    ocr_text = ocr_cfg.get("text") if ocr_cfg.get("enabled") else None

    # --- load template if needed ----------------------------------------
    template_bgr = None
    if tpl_enabled:
        tpl_name = template_cfg.get("name")
        if not tpl_name:
            raise RuntimeError("FIND_AND_SWIPE: template enabled but name missing")
        template_bgr = load_template(bank_code, tpl_name, arm_name=arm_name)
        if template_bgr is None:
            raise RuntimeError("FIND_AND_SWIPE: template '%s' not found" % tpl_name)

    if combine in ("ocr_only", "template_then_ocr") and not ocr_text:
        raise RuntimeError("FIND_AND_SWIPE: combine=%s but ocr.text missing" % combine)

    # --- recorded swipe + arm safety bounds -----------------------------
    sx_rec, sy_rec, ex_rec, ey_rec = recorded_swipe
    offset_x = ex_rec - sx_rec
    offset_y = ey_rec - sy_rec
    recorded_distance = (offset_x ** 2 + offset_y ** 2) ** 0.5

    # Camera anchor: explicit arg > config field > legacy fallback to swipe
    # start. This lets the operator decouple "where to look from" and
    # "where the slider should be" while staying compatible with old steps
    # that didn't have camera_anchor_mm in their description JSON.
    if camera_anchor is None:
        cfg_anchor = config.get("camera_anchor_mm")
        if cfg_anchor and len(cfg_anchor) == 2:
            camera_anchor = (float(cfg_anchor[0]), float(cfg_anchor[1]))
        else:
            camera_anchor = (sx_rec, sy_rec)
    cam_anchor_x, cam_anchor_y = camera_anchor

    arm_id = await _get_arm_id_for_station(station_id)
    if arm_id is None:
        raise RuntimeError("FIND_AND_SWIPE: station %d not found" % station_id)
    max_x, max_y = await _get_arm_limits(arm_id)

    diagnostics_attempts = []

    for offset_idx, (dx, dy) in enumerate(offsets):
        cam_x = _clamp(cam_anchor_x + dx, 0.0, max_x)
        cam_y = _clamp(cam_anchor_y + dy, 0.0, max_y)

        await _hw(executor, arm.move, cam_x, cam_y)
        await asyncio.sleep(retry_delay_ms / 1000.0)

        frame = await _hw(executor, cam.capture_fresh)
        if frame is None:
            logger.warning("FIND_AND_SWIPE: capture failed at (%.1f, %.1f)", cam_x, cam_y)
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

        log_extras = []
        if "best_template_score" in loc:
            log_extras.append("tpl_best=%.3f" % loc["best_template_score"])
        if "template_candidates" in loc:
            log_extras.append("tpl_cands=%d" % loc["template_candidates"])
        if "ocr_verified" in loc:
            log_extras.append("ocr_verified=%d" % loc["ocr_verified"])
        if loc.get("found"):
            log_extras.append("score=%.3f" % loc["score"])
        logger.info(
            "FIND_AND_SWIPE: attempt %d/%d cam=(%.1f,%.1f) found=%s reason=%s%s",
            offset_idx + 1, len(offsets), cam_x, cam_y,
            attempt_diag["found"], attempt_diag["reason"],
            (" " + " ".join(log_extras)) if log_extras else "")

        if not loc.get("found"):
            continue

        # --- compute new swipe coords ----------------------------------
        sx_new, sy_new = await calibration.pixel_to_arm(
            station_id, loc["rotated_px"], loc["rotated_py"], cam_x, cam_y)
        ex_unclamped = sx_new + offset_x
        ey_unclamped = sy_new + offset_y
        ex_new = _clamp(ex_unclamped, 0.0, max_x)
        ey_new = _clamp(ey_unclamped, 0.0, max_y)

        actual_distance = ((ex_new - sx_new) ** 2 + (ey_new - sy_new) ** 2) ** 0.5
        clamp_warning = None
        if recorded_distance > 0.1:
            ratio = actual_distance / recorded_distance
            if ratio < SWIPE_SHRINK_WARN_RATIO:
                clamp_warning = (
                    "swipe distance shrunk to %.1f%% of recorded after clamp "
                    "(recorded=%.1fmm, actual=%.1fmm). Slider may not trigger."
                    % (ratio * 100, recorded_distance, actual_distance))
                logger.warning("FIND_AND_SWIPE: %s", clamp_warning)

        result = {
            "found": True,
            "attempts": offset_idx + 1,
            "score": loc["score"],
            "method": loc["method"],
            "candidates": loc["candidates"],
            "rotated_px": loc["rotated_px"],
            "rotated_py": loc["rotated_py"],
            "sx_new": sx_new,
            "sy_new": sy_new,
            "ex_new": ex_new,
            "ey_new": ey_new,
            "offset_applied": [offset_x, offset_y],
            "recorded_distance_mm": round(recorded_distance, 2),
            "actual_distance_mm": round(actual_distance, 2),
            "clamp_warning": clamp_warning,
            "ocr_text": loc.get("ocr_text"),
            "diagnostics": diagnostics_attempts,
        }

        if swipe_after_find:
            await _hw(executor, arm.swipe, sx_new, sy_new, ex_new, ey_new)
            result["swiped"] = True
        else:
            result["swiped"] = False

        return result

    # All retries exhausted
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
        "FIND_AND_SWIPE: not found after %d attempt(s) — reason=%s combine=%s threshold=%.2f%s"
        % (len(offsets), last.get("reason", "unknown"), combine, threshold, detail))
