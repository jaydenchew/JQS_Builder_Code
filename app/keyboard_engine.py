"""Intelligent keyboard input engine — handles multi-page keyboards with auto page-switching and shift logic.

type_with_intelligent_keyboard accepts optional arm and executor parameters for non-blocking operation.
"""
import asyncio
import time
import json
import logging
from app import arm_client as _arm_mod, database
from app.config import ARM_DIGIT_DELAY

logger = logging.getLogger(__name__)

PAGE_SWITCH_DELAY = 0.3
SHIFT_DELAY = 0.2


class KeyboardConfig:
    """Parsed keyboard configuration with page navigation helpers"""

    def __init__(self, raw_config: dict):
        self.properties = raw_config.get("properties", {})
        self.pages = raw_config.get("pages", {})
        self.char_to_page = raw_config.get("char_to_page", {})

        self.auto_capitalize_first = self.properties.get("auto_capitalize_first", False)
        self.shift_auto_cancel = self.properties.get("shift_auto_cancel_after_one", True)

        self._char_page_cache = self._build_char_page_map()

    def _build_char_page_map(self) -> dict:
        mapping = {}
        for char_range, page_name in self.char_to_page.items():
            if len(char_range) == 3 and char_range[1] == "-":
                start, end = char_range[0], char_range[2]
                for c in range(ord(start), ord(end) + 1):
                    mapping[chr(c)] = page_name
            else:
                for c in char_range:
                    mapping[c] = page_name
        return mapping

    def get_page_for_char(self, char: str) -> str | None:
        if char in self._char_page_cache:
            return self._char_page_cache[char]
        lower = char.lower()
        if lower in self._char_page_cache:
            page = self._char_page_cache[lower]
            if char.isupper() and page == "abc":
                return "abc+shift"
            return page
        return None

    def get_key_coords(self, page: str, key: str) -> tuple[float, float]:
        actual_page = "abc" if page == "abc+shift" else page
        page_data = self.pages.get(actual_page)
        if not page_data:
            raise RuntimeError("Keyboard page '%s' not found in config" % actual_page)
        keys = page_data.get("keys", {})
        if key not in keys:
            raise RuntimeError("Key '%s' not found on page '%s'" % (key, actual_page))
        coords = keys[key]
        return float(coords[0]), float(coords[1])

    def get_switch_key(self, from_page: str, to_page: str) -> str | None:
        actual_from = "abc" if from_page == "abc+shift" else from_page
        actual_to = "abc" if to_page == "abc+shift" else to_page

        if actual_from == actual_to:
            return None

        target_page_data = self.pages.get(actual_to, {})
        switch_field = "switch_from_%s" % actual_from
        switch_key = target_page_data.get(switch_field)
        if switch_key:
            return switch_key

        for mid_page_name, mid_page_data in self.pages.items():
            if mid_page_name in (actual_from, actual_to):
                continue
            step1 = mid_page_data.get("switch_from_%s" % actual_from)
            step2 = target_page_data.get("switch_from_%s" % mid_page_name)
            if step1 and step2:
                return step1

        return None

    def get_default_page(self) -> str:
        for page_name, page_data in self.pages.items():
            if page_data.get("is_default"):
                return page_name
        return "abc"


async def load_keyboard_config(bank_code: str, station_id: int, keyboard_type: str):
    """Load keyboard config. Returns KeyboardConfig for multi-page keyboards,
    a raw dict for random_pin, or None for simple keyboards and missing entries.

    When a row exists but the config only carries a category marker (e.g.,
    `{"category": "app_keypad"}` for a simple keypad whose coords live in the
    keymaps table), return None so execute_type falls through to lookup_keymap.
    Without this fallthrough, the caller would build an empty KeyboardConfig
    and crash inside type_with_intelligent_keyboard.
    """
    row = await database.fetchone(
        "SELECT config FROM keyboard_configs WHERE bank_code = %s AND station_id = %s AND keyboard_type = %s",
        (bank_code, station_id, keyboard_type),
    )
    if not row:
        return None
    raw = row["config"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    if raw.get("type") == "random_pin":
        return raw
    if not raw.get("pages"):
        return None
    return KeyboardConfig(raw)


async def type_with_random_pin(config: dict, text: str, arm=None, cam=None, executor=None):
    """Type on a randomized PIN keypad using Tesseract per-cell OCR.

    Uses recorded arm coordinates to locate each grid cell in the photo,
    then identifies digits via Tesseract with multiple preprocessing methods.
    Falls back to additional camera positions if target digit not found.

    config: {
        "type": "random_pin",
        "camera_pos": [x, y],
        "positions": [[x1,y1], ... 12 positions in arm coords],
        "roi": {...}  (unused in Tesseract approach)
    }
    """
    import cv2
    import numpy as np
    import pytesseract
    from app.config import TESSERACT_CMD
    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

    a = arm if arm is not None else _arm_mod
    c = cam
    if c is None:
        raise RuntimeError("Camera required for random_pin keyboard")

    positions = config["positions"]
    camera_pos = config.get("camera_pos", [91, 58])
    station_id = config.get("station_id", 1)
    CELL_HALF = 28

    from app import calibration
    cal = await calibration.get_calibration(station_id)
    if not cal:
        raise RuntimeError("Calibration required for random_pin (station %d)" % station_id)

    M = np.array(cal["transform_matrix"])
    park_x, park_y = cal.get("camera_park_pos", [91.0, 58.0])
    raw_height = cal.get("raw_height", 480)
    s = cal.get("scale_mm_per_pixel", 0.204)
    tx, ty = M[0][2], M[1][2]

    target_digits = set(text)
    camera_offsets = [(0, 0), (-2, 0), (0, -2)]

    # Index 9 = backspace (-) and index 11 = enter (+) are fixed non-digit keys.
    # Index 10 = digit 0, must be included. Scan all 12 cells except these two.
    _DIGIT_SKIP = {9, 11}

    digit_to_cell = {}
    _first_wide_frame = None  # kept for annotated screenshot saved to transaction_logs

    for offset_idx, (dx, dy) in enumerate(camera_offsets):
        cam_x = camera_pos[0] + dx
        cam_y = camera_pos[1] + dy

        await _hw(executor, a.move, cam_x, cam_y)
        await asyncio.sleep(0.8)

        frame = await _hw(executor, c.capture_frame)
        if frame is None:
            logger.warning("random_pin: capture failed at (%.0f,%.0f)", cam_x, cam_y)
            continue
        if _first_wide_frame is None:
            _first_wide_frame = frame  # save first frame for annotated debug image

        rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)

        for i, (ax, ay) in enumerate(positions[:12]):
            if i in _DIGIT_SKIP:
                continue
            if any(ax == pos[0] and ay == pos[1] for d, pos in digit_to_cell.values()):
                continue

            abx = ax - (cam_x - park_x)
            aby = ay - (cam_y - park_y)
            ry = (tx - abx) / s
            rx = (aby - ty) / s
            px, py = int(raw_height - 1 - ry), int(rx)

            h, w = rotated.shape[:2]
            y1 = max(0, py - CELL_HALF)
            y2 = min(h, py + CELL_HALF)
            x1 = max(0, px - CELL_HALF)
            x2 = min(w, px + CELL_HALF)
            cell = rotated[y1:y2, x1:x2]
            if cell.size == 0:
                continue

            gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
            digit = _tesseract_recognize_digit(gray, pytesseract)
            if digit and digit not in digit_to_cell:
                digit_to_cell[digit] = (i, [ax, ay])

        logger.info("random_pin: pos %d (%.0f,%.0f) recognized %d digits: %s",
                     offset_idx + 1, cam_x, cam_y, len(digit_to_cell), sorted(digit_to_cell.keys()))

        if target_digits.issubset(digit_to_cell.keys()):
            break

        # Early elimination: if exactly 1 target digit and 1 unassigned cell remain
        # after this wide-view pass, we can resolve without further passes or close-up.
        _early_missing = target_digits - digit_to_cell.keys()
        if len(_early_missing) == 1:
            _early_unassigned = [(i, p) for i, p in enumerate(positions[:12])
                                 if i not in _DIGIT_SKIP
                                 and i not in {idx for idx, _ in digit_to_cell.values()}]
            if len(_early_unassigned) == 1:
                d = next(iter(_early_missing))
                i, pos = _early_unassigned[0]
                digit_to_cell[d] = (i, list(pos))
                logger.info("random_pin: early elimination '%s' at pos %d (cell %d)",
                            d, offset_idx + 1, i + 1)
                break

    # Close-up fallback: for any remaining unrecognized cells, fly the camera
    # directly above that cell so the digit fills the frame center. Uses inverse
    # calibration to compute the cam position that places the cell at the image
    # center, then OCRs only that center crop. If exactly one digit + one cell
    # remain after the loop, resolve by elimination without an extra move.
    missing = target_digits - digit_to_cell.keys()
    if missing:
        assigned = {idx for idx, _ in digit_to_cell.values()}
        for i, (ax, ay) in enumerate(positions[:12]):
            if i in _DIGIT_SKIP or i in assigned:
                continue
            # Inverse calibration: find cam position that centres (ax,ay) in frame.
            # Forward: px = raw_height-1 - (tx-abx)/s, py = (aby-ty)/s
            # Solve for cam_x/cam_y when px=rot_w//2, py=rot_h//2:
            #   ry = raw_height-1 - (rot_w//2)
            #   rx = rot_h//2
            #   abx = tx - ry*s,  aby = ty + rx*s
            #   cam_x = park_x + ax - abx,  cam_y = park_y + ay - aby
            # rot dimensions come from a real frame captured below; use 480/640
            # defaults (ROTATE_90_CW on a 480×640 raw → 640h×480w) until then.
            ry_t = raw_height - 1 - 240   # 240 = 480//2, rotated image width center
            rx_t = 320                     # rotated image height center (640//2)
            abx_t = tx - ry_t * s
            aby_t = ty + rx_t * s
            cu_x = park_x + ax - abx_t
            cu_y = park_y + ay - aby_t

            # Warn if the close-up position looks far outside the original
            # camera_pos range (likely exceeds arm travel limits for this machine).
            # We don't have max_x/max_y here, so use camera_pos as a reference.
            if cu_x < 0 or cu_y < 0 or cu_x > camera_pos[0] + 30 or cu_y > camera_pos[1] + 30:
                logger.warning("random_pin close-up: cell %d cam=(%.1f,%.1f) may exceed arm limits, skipping",
                               i + 1, cu_x, cu_y)
                continue

            await _hw(executor, a.move, cu_x, cu_y)
            await asyncio.sleep(0.8)

            frame = await _hw(executor, c.capture_fresh)
            if frame is None:
                continue
            rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            rot_h, rot_w = rotated.shape[:2]
            cy, cx = rot_h // 2, rot_w // 2
            CLOSEUP_HALF = 50
            cell = rotated[max(0, cy - CLOSEUP_HALF):cy + CLOSEUP_HALF,
                           max(0, cx - CLOSEUP_HALF):cx + CLOSEUP_HALF]
            if cell.size == 0:
                continue
            gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
            digit = _tesseract_recognize_digit(gray, pytesseract)
            logger.info("random_pin close-up: cell %d arm=(%.1f,%.1f) cam=(%.1f,%.1f) digit=%s",
                        i + 1, ax, ay, cu_x, cu_y, digit)
            if digit and digit not in digit_to_cell:
                digit_to_cell[digit] = (i, [ax, ay])
                assigned.add(i)
                missing = target_digits - digit_to_cell.keys()
                if not missing:
                    break

        # Elimination: if exactly one digit and one unassigned cell remain, lock.
        missing = target_digits - digit_to_cell.keys()
        if len(missing) == 1:
            unassigned = [(i, p) for i, p in enumerate(positions[:12])
                          if i not in _DIGIT_SKIP and i not in {idx for idx, _ in digit_to_cell.values()}]
            if len(unassigned) == 1:
                d = next(iter(missing))
                i, pos = unassigned[0]
                digit_to_cell[d] = (i, list(pos))
                logger.info("random_pin: resolved '%s' by elimination (cell %d)", d, i + 1)

    if not target_digits.issubset(digit_to_cell.keys()):
        missing = target_digits - set(digit_to_cell.keys())
        raise RuntimeError("random_pin: could not find digits %s after close-up fallback" % (missing,))

    logger.info("random_pin: typing '%s'", text)
    for ch in text:
        _, (ax, ay) = digit_to_cell[ch]
        await _hw(executor, a.click, ax, ay)
        await asyncio.sleep(ARM_DIGIT_DELAY)

    logger.info("random_pin: typed %d digits successfully", len(text))

    # Build annotated debug image: draw each cell box with its recognized digit (or ?).
    # Returned as base64 JPEG so execute_type can pass it to transaction_logs.screenshot_base64.
    if _first_wide_frame is not None:
        try:
            import base64 as _b64
            ann = cv2.rotate(_first_wide_frame, cv2.ROTATE_90_CLOCKWISE)
            h_ann, w_ann = ann.shape[:2]
            cell_to_digit = {idx: d for d, (idx, _) in digit_to_cell.items()}
            ann_cam_x, ann_cam_y = camera_pos[0], camera_pos[1]
            for i, (ax, ay) in enumerate(positions[:12]):
                if i in _DIGIT_SKIP:
                    continue
                abx = ax - (ann_cam_x - park_x)
                aby = ay - (ann_cam_y - park_y)
                ry = (tx - abx) / s
                rx = (aby - ty) / s
                px_a = int(raw_height - 1 - ry)
                py_a = int(rx)
                x1 = max(0, px_a - CELL_HALF); x2 = min(w_ann, px_a + CELL_HALF)
                y1 = max(0, py_a - CELL_HALF); y2 = min(h_ann, py_a + CELL_HALF)
                d = cell_to_digit.get(i)
                color = (0, 200, 0) if d else (0, 0, 220)
                cv2.rectangle(ann, (x1, y1), (x2, y2), color, 2)
                cv2.putText(ann, d if d else "?", (x1 + 3, y1 + 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2)
            _, buf = cv2.imencode(".jpg", ann, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return _b64.b64encode(buf).decode("utf-8")
        except Exception as ann_err:
            logger.warning("random_pin: annotated screenshot failed: %s", ann_err)
    return None


def _tesseract_recognize_digit(gray_cell, pytesseract):
    """Try multiple preprocessing methods on a grayscale cell image, return single digit or None."""
    import cv2
    blurred = cv2.GaussianBlur(gray_cell, (3, 3), 0)
    methods = [
        cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5),
        cv2.threshold(gray_cell, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        cv2.threshold(gray_cell, 150, 255, cv2.THRESH_BINARY)[1],
        gray_cell,
    ]
    for proc in methods:
        big = cv2.resize(proc, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        bordered = cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        result = pytesseract.image_to_string(bordered,
            config="--psm 10 -c tessedit_char_whitelist=0123456789").strip()
        if result and result.isdigit() and len(result) == 1:
            return result
    return None


async def _hw(executor, func, *args):
    if executor is None:
        return func(*args)
    return await asyncio.get_event_loop().run_in_executor(executor, func, *args)


async def type_with_intelligent_keyboard(kb_config: KeyboardConfig, text: str, arm=None, executor=None):
    """Type a string using intelligent page-switching."""
    a = arm if arm is not None else _arm_mod
    current_page = kb_config.get_default_page()

    CHAR_ALIASES = {' ': 'space', '\n': 'enter', '\t': 'tab'}
    for char_index, char in enumerate(text):
        lookup_char = CHAR_ALIASES.get(char, char)
        target_page = kb_config.get_page_for_char(char) or kb_config.get_page_for_char(lookup_char)

        if target_page is None:
            for pname, pdata in kb_config.pages.items():
                if lookup_char in pdata.get("keys", {}):
                    target_page = pname
                    break

        if target_page is None:
            logger.warning("Character '%s' has no page mapping, skipping", char)
            continue

        actual_char = char.lower() if target_page == "abc+shift" else lookup_char
        needs_shift = target_page == "abc+shift"
        target_base = "abc" if needs_shift else target_page

        if target_base != (current_page if current_page != "abc+shift" else "abc"):
            await _switch_pages(kb_config, current_page, target_base, a, executor)
            current_page = target_base

        if needs_shift:
            if char_index == 0 and kb_config.auto_capitalize_first:
                pass
            else:
                sx, sy = kb_config.get_key_coords("abc", "shift")
                await _hw(executor, a.click, sx, sy)
                await asyncio.sleep(SHIFT_DELAY)

        cx, cy = kb_config.get_key_coords(current_page, actual_char)
        await _hw(executor, a.click, cx, cy)
        await asyncio.sleep(ARM_DIGIT_DELAY)

        if needs_shift:
            current_page = "abc"

    logger.info("Intelligent keyboard typed %d characters", len(text))


async def _switch_pages(kb_config: KeyboardConfig, from_page: str, to_page: str, arm, executor=None):
    actual_from = "abc" if from_page == "abc+shift" else from_page

    target_page_data = kb_config.pages.get(to_page, {})
    direct_key = target_page_data.get("switch_from_%s" % actual_from)

    if direct_key:
        kx, ky = kb_config.get_key_coords(actual_from, direct_key)
        await _hw(executor, arm.click, kx, ky)
        await asyncio.sleep(PAGE_SWITCH_DELAY)
        return

    for mid_name, mid_data in kb_config.pages.items():
        if mid_name in (actual_from, to_page):
            continue
        step1_key = mid_data.get("switch_from_%s" % actual_from)
        step2_key = target_page_data.get("switch_from_%s" % mid_name)
        if step1_key and step2_key:
            k1x, k1y = kb_config.get_key_coords(actual_from, step1_key)
            await _hw(executor, arm.click, k1x, k1y)
            await asyncio.sleep(PAGE_SWITCH_DELAY)
            k2x, k2y = kb_config.get_key_coords(mid_name, step2_key)
            await _hw(executor, arm.click, k2x, k2y)
            await asyncio.sleep(PAGE_SWITCH_DELAY)
            return

    raise RuntimeError("No switch path from page '%s' to '%s'" % (actual_from, to_page))
