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

    digit_to_cell = {}

    for offset_idx, (dx, dy) in enumerate(camera_offsets):
        cam_x = camera_pos[0] + dx
        cam_y = camera_pos[1] + dy

        await _hw(executor, a.move, cam_x, cam_y)
        await asyncio.sleep(0.8)

        frame = await _hw(executor, c.capture_frame)
        if frame is None:
            logger.warning("random_pin: capture failed at (%.0f,%.0f)", cam_x, cam_y)
            continue

        rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)

        for i, (ax, ay) in enumerate(positions[:10]):
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

    if not target_digits.issubset(digit_to_cell.keys()):
        missing = target_digits - set(digit_to_cell.keys())
        # Save debug images so we can inspect what the camera actually captured
        # and what each cell crop looked like.
        try:
            import os, datetime
            debug_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "deploy", "logs", "random_pin_debug")
            os.makedirs(debug_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            label_list = ['8','0','6','5','9','1','2','4','3','X','7','OK']
            for offset_idx, (dx, dy) in enumerate(camera_offsets):
                cam_x = camera_pos[0] + dx
                cam_y = camera_pos[1] + dy
                await _hw(executor, a.move, cam_x, cam_y)
                await asyncio.sleep(0.8)
                frame = await _hw(executor, c.capture_frame)
                if frame is None:
                    continue
                rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                # Save full rotated image with cell boxes drawn
                vis = rotated.copy()
                h_img, w_img = vis.shape[:2]
                for i, (ax, ay) in enumerate(positions[:10]):
                    abx = ax - (cam_x - park_x)
                    aby = ay - (cam_y - park_y)
                    ry = (tx - abx) / s
                    rx = (aby - ty) / s
                    px_c = int(raw_height - 1 - ry)
                    py_c = int(rx)
                    x1 = max(0, px_c - CELL_HALF); x2 = min(w_img, px_c + CELL_HALF)
                    y1 = max(0, py_c - CELL_HALF); y2 = min(h_img, py_c + CELL_HALF)
                    cell = rotated[y1:y2, x1:x2]
                    lbl = label_list[i] if i < len(label_list) else str(i)
                    color = (0, 255, 0) if lbl in digit_to_cell else (0, 0, 255)
                    cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(vis, lbl, (x1 + 2, y1 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                    # Save individual cell crop with all preprocessing stages
                    if cell.size > 0:
                        gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
                        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
                        stages = [
                            ("raw", gray),
                            ("otsu", cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]),
                            ("adapt", cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5)),
                            ("thresh150", cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)[1]),
                        ]
                        row_imgs = [cv2.resize(img, (112, 112)) for _, img in stages]
                        strip = np.hstack(row_imgs)
                        fn = os.path.join(debug_dir, "%s_off%d_cell%s.jpg" % (ts, offset_idx + 1, lbl))
                        cv2.imwrite(fn, strip)
                cv2.imwrite(os.path.join(debug_dir, "%s_off%d_full.jpg" % (ts, offset_idx + 1)), vis)
            logger.info("random_pin: debug images saved to %s", debug_dir)
        except Exception as dbg_err:
            logger.warning("random_pin: debug save failed: %s", dbg_err)
        raise RuntimeError("random_pin: could not find digits %s after %d positions" % (missing, len(camera_offsets)))

    logger.info("random_pin: typing '%s'", text)
    for ch in text:
        _, (ax, ay) = digit_to_cell[ch]
        await _hw(executor, a.click, ax, ay)
        await asyncio.sleep(ARM_DIGIT_DELAY)

    logger.info("random_pin: typed %d digits successfully", len(text))


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
