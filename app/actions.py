"""Action executors for each flow step action_type.

All execute_* functions accept optional `arm`, `cam`, and `executor` parameters.
- arm/cam: ArmClient/Camera instances (defaults to module-level)
- executor: ThreadPoolExecutor for running blocking arm/camera calls without freezing the event loop
Hardware calls (arm.click, camera.capture) run in executor threads.
DB calls remain async. time.sleep replaced with asyncio.sleep.
"""
import asyncio
import time
import logging
import cv2
from app import arm_client as _arm_mod, camera as _cam_mod, database
from app.config import ARM_DIGIT_DELAY

logger = logging.getLogger(__name__)


def _arm(inst):
    return inst if inst is not None else _arm_mod

def _cam(inst):
    return inst if inst is not None else _cam_mod


async def _hw(executor, func, *args):
    """Run a blocking hardware function in a thread executor."""
    if executor is None:
        return func(*args)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args)


async def lookup_ui_element(bank_code: str, station_id: int, element_key: str):
    row = await database.fetchone(
        "SELECT x, y FROM ui_elements WHERE bank_code = %s AND station_id = %s AND element_key = %s",
        (bank_code, station_id, element_key),
    )
    if not row:
        row = await database.fetchone(
            "SELECT x, y FROM ui_elements WHERE bank_code IS NULL AND station_id = %s AND element_key = %s",
            (station_id, element_key),
        )
    if not row:
        raise ValueError("UI element not found: %s/%s/%s" % (bank_code, station_id, element_key))
    return float(row["x"]), float(row["y"])


async def lookup_keymap(bank_code: str, station_id: int, keyboard_type: str):
    rows = await database.fetchall(
        "SELECT key_char, x, y FROM keymaps WHERE bank_code = %s AND station_id = %s AND keyboard_type = %s",
        (bank_code, station_id, keyboard_type),
    )
    if not rows:
        raise ValueError("Keymap not found: %s/%s/%s" % (bank_code, station_id, keyboard_type))
    return {r["key_char"]: (float(r["x"]), float(r["y"])) for r in rows}


async def lookup_swipe(bank_code: str, station_id: int, swipe_key: str):
    row = await database.fetchone(
        "SELECT start_x, start_y, end_x, end_y FROM swipe_actions WHERE bank_code = %s AND station_id = %s AND swipe_key = %s",
        (bank_code, station_id, swipe_key),
    )
    if not row:
        row = await database.fetchone(
            "SELECT start_x, start_y, end_x, end_y FROM swipe_actions WHERE bank_code IS NULL AND station_id = %s AND swipe_key = %s",
            (station_id, swipe_key),
        )
    if not row:
        raise ValueError("Swipe not found: %s/%s/%s" % (bank_code, station_id, swipe_key))
    return float(row["start_x"]), float(row["start_y"]), float(row["end_x"]), float(row["end_y"])


async def get_dynamic_value(input_source: str, transaction: dict, password: str, bank_code: str = None):
    if input_source == "pay_to_account_no":
        return str(transaction["pay_to_account_no"])
    elif input_source == "amount":
        amt = transaction["amount"]
        fmt = transaction.get("_amount_format") or "decimal"
        if fmt == "no_dot":
            return str(int(round(float(amt) * 100)))
        elif fmt == "always_decimal":
            return "%.2f" % float(amt)
        else:
            if amt == int(amt):
                return str(int(amt))
            return str(amt)
    elif input_source == "password":
        return password
    elif input_source == "pin":
        return str(transaction.get("pin", ""))
    elif input_source == "pay_to_account_name":
        return str(transaction["pay_to_account_name"])
    elif input_source == "pay_to_bank_name":
        from_code = bank_code or transaction.get("pay_from_bank_code")
        to_code = transaction["pay_to_bank_code"]
        row = await database.fetchone(
            "SELECT search_text FROM bank_name_mappings WHERE from_bank_code = %s AND to_bank_code = %s",
            (from_code, to_code),
        )
        if not row:
            raise RuntimeError("No bank name mapping: %s -> %s" % (from_code, to_code))
        return row["search_text"]
    elif input_source == "fixed_text":
        return str(transaction.get("_step_description", ""))
    else:
        raise ValueError("Unknown input_source: %s" % input_source)


async def execute_click(step, bank_code, station_id, transaction, password, arm=None, cam=None, executor=None):
    a = _arm(arm)
    x, y = await lookup_ui_element(bank_code, station_id, step["ui_element_key"])
    tap_count = step.get("tap_count", 1) or 1
    for i in range(tap_count):
        await _hw(executor, a.click, x, y)
        if i < tap_count - 1:
            await asyncio.sleep(3)
    logger.info("CLICK %s at (%.1f, %.1f) x%d", step["ui_element_key"], x, y, tap_count)


async def execute_type(step, bank_code, station_id, transaction, password, arm=None, cam=None, executor=None):
    from app.keyboard_engine import load_keyboard_config, type_with_intelligent_keyboard, type_with_random_pin

    a = _arm(arm)
    c = _cam(cam)
    transaction["_step_description"] = step.get("description", "")
    text = await get_dynamic_value(step["input_source"], transaction, password, bank_code)
    keyboard_type = step["keymap_type"]

    kb_config = await load_keyboard_config(bank_code, station_id, keyboard_type)
    if kb_config and isinstance(kb_config, dict) and kb_config.get("type") == "random_pin":
        kb_config["station_id"] = station_id
        logger.info("TYPE '%s' using random_pin keyboard (%s)", text, keyboard_type)
        await type_with_random_pin(kb_config, text, arm=a, cam=c, executor=executor)
    elif kb_config:
        logger.info("TYPE '%s' using intelligent keyboard (%s)", text, keyboard_type)
        await type_with_intelligent_keyboard(kb_config, text, arm=a, executor=executor)
    else:
        keymap = await lookup_keymap(bank_code, station_id, keyboard_type)
        logger.info("TYPE '%s' using simple keymap (%s)", text, keyboard_type)
        CHAR_ALIASES = {' ': 'space', '\n': 'enter', '\t': 'tab'}
        for ch in text:
            key = CHAR_ALIASES.get(ch, ch)
            if key in keymap:
                x, y = keymap[key]
                await _hw(executor, a.click, x, y)
                await asyncio.sleep(ARM_DIGIT_DELAY)
            else:
                logger.warning("Key '%s' not in keymap, skipping", ch)


async def execute_swipe(step, bank_code, station_id, transaction, password, arm=None, cam=None, executor=None):
    a = _arm(arm)
    sx, sy, ex, ey = await lookup_swipe(bank_code, station_id, step["swipe_key"])
    await _hw(executor, a.swipe, sx, sy, ex, ey)
    logger.info("SWIPE %s (%.1f,%.1f)->(%.1f,%.1f)", step["swipe_key"], sx, sy, ex, ey)


async def execute_photo(step, bank_code, station_id, transaction, password, arm=None, cam=None, executor=None):
    a = _arm(arm)
    c = _cam(cam)
    x, y = await lookup_ui_element(bank_code, station_id, step["ui_element_key"])
    await _hw(executor, a.move, x, y)
    await asyncio.sleep(step.get("pre_delay_ms", 5000) / 1000.0)
    b64 = await _hw(executor, c.capture_base64)
    if b64:
        await database.execute(
            "UPDATE transactions SET receipt_base64 = %s WHERE id = %s",
            (b64, transaction["id"]),
        )
        logger.info("PHOTO captured and stored for transaction %d", transaction["id"])
    else:
        logger.error("PHOTO capture failed")
    return b64


async def execute_arm_move(step, bank_code, station_id, transaction, password, arm=None, cam=None, executor=None):
    a = _arm(arm)
    if step.get("ui_element_key"):
        x, y = await lookup_ui_element(bank_code, station_id, step["ui_element_key"])
        await _hw(executor, a.move, x, y)
        logger.info("ARM_MOVE to %s (%.1f, %.1f)", step["ui_element_key"], x, y)


async def execute_ocr_verify(step, bank_code, station_id, transaction, password, arm=None, cam=None, executor=None):
    """OCR verification. Stores result in transaction['_ocr_result'] for arm_worker to read.

    _ocr_result = {
        "success": bool,
        "receipt_result": "success"/"fail"/"review"/None,
        "screenshot_b64": str,
        "ocr_text": str,
        "is_receipt_check": bool  (True = post-transfer, False = pre-transfer)
    }
    """
    import json as _json
    from app import ocr

    a = _arm(arm)
    c = _cam(cam)

    if ocr.get_reader() is None:
        from app.config import OCR_REQUIRED
        if OCR_REQUIRED:
            raise RuntimeError("OCR engine not available — install easyocr or pytesseract")
        logger.warning("OCR engine missing, skipping verification (OCR_REQUIRED=false)")
        return True

    x, y = await lookup_ui_element(bank_code, station_id, step["ui_element_key"])
    await _hw(executor, a.move, x, y)
    await asyncio.sleep(2)

    ocr_config = None
    if step.get("description"):
        try:
            ocr_config = _json.loads(step["description"])
        except (_json.JSONDecodeError, TypeError) as e:
            logger.warning("OCR config parse failed for step %s: %s", step.get("step_name"), e)

    frame = await _hw(executor, c.capture_fresh)
    start_time = time.time()

    is_receipt_check = bool(ocr_config and ocr_config.get("receipt_status"))

    if ocr_config is not None:
        tx_values = {
            "pay_to_account_no": str(transaction.get("pay_to_account_no", "")),
            "amount": str(transaction.get("amount", "")),
            "pay_to_account_name": str(transaction.get("pay_to_account_name", "")),
        }
        success, ocr_text, screenshot_b64, receipt_result, ocr_meta = await _hw(
            executor, ocr.verify_configurable, frame, ocr_config, tx_values
        )
        expected_str = "fields=%s" % ocr_config.get("verify_fields", [])
        if receipt_result:
            expected_str += " receipt=%s" % receipt_result
    else:
        expected_account = str(transaction["pay_to_account_no"])
        expected_amount = str(transaction["amount"])
        success, ocr_text, screenshot_b64, receipt_result, ocr_meta = await _hw(
            executor, ocr.verify_transfer_from_frame, frame, expected_account, expected_amount
        )
        expected_str = "account=%s amount=%s" % (expected_account, expected_amount)

    duration_ms = int((time.time() - start_time) * 1000)

    # Persist ocr_meta JSON to transaction_logs.message for observability.
    # On failure we still prepend the raw ocr_text so operators can grep for it.
    meta_json = _json.dumps(ocr_meta) if ocr_meta else None
    if success:
        message_value = meta_json
    else:
        message_value = "%s | meta=%s" % (ocr_text, meta_json) if meta_json else ocr_text

    await database.execute(
        """INSERT INTO transaction_logs 
        (transaction_id, step_number, step_name, action_type, result, duration_ms, 
         screenshot_base64, ocr_text, expected_value, message)
        VALUES (%s, %s, %s, 'OCR_VERIFY', %s, %s, %s, %s, %s, %s)""",
        (transaction["id"], step["step_number"], step["step_name"],
         "ok" if success else "fail", duration_ms, screenshot_b64, ocr_text,
         expected_str, message_value),
    )

    transaction["_ocr_result"] = {
        "success": success,
        "receipt_result": receipt_result,
        "screenshot_b64": screenshot_b64,
        "ocr_text": ocr_text,
        "is_receipt_check": is_receipt_check,
        "ocr_meta": ocr_meta,
    }

    if not success:
        logger.error("OCR verification failed: %s", ocr_text[:200])
        raise RuntimeError("OCR_VERIFY failed: %s" % ocr_text[:200])

    logger.info("OCR verification passed (took %dms) receipt=%s", duration_ms, receipt_result)
    return True


async def execute_check_screen(step, bank_code, station_id, transaction, password, arm=None, cam=None, executor=None):
    import json as _json
    from app import screen_checker

    a = _arm(arm)
    c = _cam(cam)

    config = screen_checker.parse_check_config(step.get("description"))
    if not config or not config.get("reference"):
        logger.warning("CHECK_SCREEN: no config or reference, skipping")
        return True

    ref_name = config["reference"]
    threshold = config.get("threshold", screen_checker.DEFAULT_SSIM_THRESHOLD)
    max_retries = config.get("max_retries", 3)
    handler_flow = config.get("handler_flow", "")
    roi = config.get("roi")

    arm_name = transaction.get("_arm_name")
    reference = screen_checker.load_reference(bank_code, ref_name, arm_name=arm_name)
    if reference is None:
        raise RuntimeError("CHECK_SCREEN: reference image '%s' not found for %s" % (ref_name, bank_code))

    cam_x, cam_y = await lookup_ui_element(bank_code, station_id, step["ui_element_key"])
    await _hw(executor, a.move, cam_x, cam_y)
    await asyncio.sleep(1)

    start_time = time.time()
    score = 0.0
    last_result = None

    for attempt in range(1, max_retries + 1):
        frame = await _hw(executor, c.capture_fresh)
        if frame is None:
            logger.error("CHECK_SCREEN: capture failed (attempt %d/%d)", attempt, max_retries)
            await asyncio.sleep(2)
            continue

        current = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        result = screen_checker.compare_screen(current, reference, threshold, roi)
        last_result = result
        is_match = result["pass"]
        score = result["ssim"]
        logger.info(
            "CHECK_SCREEN: attempt %d/%d, ssim=%.4f inliers=%d rot=%.2fdeg valid=%.2f reason=%s threshold=%.2f match=%s",
            attempt, max_retries, result["ssim"], result["inliers"], result["rot_deg"],
            result["valid_ratio"], result["reason"], threshold, is_match,
        )

        if is_match:
            duration_ms = int((time.time() - start_time) * 1000)
            ok_msg = _json.dumps({
                "ssim": result["ssim"],
                "inliers": result["inliers"],
                "rot_deg": result["rot_deg"],
                "scale": result["scale"],
                "valid_ratio": result["valid_ratio"],
                "ms": result["ms"],
                "reason": result["reason"],
                "attempt": attempt,
                "threshold": threshold,
            })
            await database.execute(
                """INSERT INTO transaction_logs
                (transaction_id, step_number, step_name, action_type, result, duration_ms, message)
                VALUES (%s, %s, %s, 'CHECK_SCREEN', 'ok', %s, %s)""",
                (transaction["id"], step["step_number"], step["step_name"],
                 duration_ms, ok_msg)
            )
            return True

        if handler_flow and attempt < max_retries:
            logger.info("CHECK_SCREEN: popup detected, running handler flow...")
            try:
                await _run_handler_flow(handler_flow, bank_code, station_id, transaction, password, arm=a, cam=c, executor=executor)
            except Exception as e:
                logger.error("CHECK_SCREEN: handler flow failed: %s", e)
            await asyncio.sleep(1)
            await _hw(executor, a.move, cam_x, cam_y)
            await asyncio.sleep(1)

    duration_ms = int((time.time() - start_time) * 1000)
    fail_screenshot = await _hw(executor, c.capture_base64)
    fail_meta = {
        "best_ssim": score,
        "attempts": max_retries,
        "threshold": threshold,
    }
    if last_result is not None:
        fail_meta.update({
            "inliers": last_result["inliers"],
            "rot_deg": last_result["rot_deg"],
            "scale": last_result["scale"],
            "valid_ratio": last_result["valid_ratio"],
            "ms": last_result["ms"],
            "reason": last_result["reason"],
        })
    fail_msg = _json.dumps(fail_meta)
    await database.execute(
        """INSERT INTO transaction_logs
        (transaction_id, step_number, step_name, action_type, result, duration_ms, screenshot_base64, message)
        VALUES (%s, %s, %s, 'CHECK_SCREEN', 'fail', %s, %s, %s)""",
        (transaction["id"], step["step_number"], step["step_name"],
         duration_ms, fail_screenshot, fail_msg)
    )
    reason = last_result["reason"] if last_result else "no_frame"
    raise RuntimeError(
        "CHECK_SCREEN failed: screen does not match '%s' after %d attempts (best_ssim=%.4f reason=%s)"
        % (ref_name, max_retries, score, reason)
    )


async def _run_handler_flow(handler_flow_ref: str, bank_code: str, station_id: int,
                            transaction: dict, password: str, arm=None, cam=None, executor=None):
    parts = handler_flow_ref.split("__")
    template_id = int(parts[-1]) if parts[-1].isdigit() else None
    if template_id is None:
        logger.warning("CHECK_SCREEN: invalid handler_flow ref: %s", handler_flow_ref)
        return

    steps = await database.fetchall(
        "SELECT * FROM flow_steps WHERE flow_template_id = %s ORDER BY step_number", (template_id,)
    )
    if not steps:
        logger.warning("CHECK_SCREEN: handler flow %d has no steps", template_id)
        return

    handler_bank = parts[0]
    for s in steps:
        if s["step_name"] == "done":
            break
        handler = ACTION_MAP.get(s["action_type"])
        if handler:
            try:
                pre = s.get("pre_delay_ms", 0) or 0
                if pre > 0:
                    await asyncio.sleep(pre / 1000.0)
                await handler(s, handler_bank, station_id, transaction, password, arm=arm, cam=cam, executor=executor)
                post = s.get("post_delay_ms", 0) or 0
                if post > 0:
                    await asyncio.sleep(post / 1000.0)
            except Exception as e:
                logger.error("CHECK_SCREEN handler step %s failed: %s", s["step_name"], e)


ACTION_MAP = {
    "CLICK": execute_click,
    "TYPE": execute_type,
    "SWIPE": execute_swipe,
    "PHOTO": execute_photo,
    "ARM_MOVE": execute_arm_move,
    "OCR_VERIFY": execute_ocr_verify,
    "CHECK_SCREEN": execute_check_screen,
}


async def execute_step(step, bank_code, station_id, transaction, password, transaction_id,
                       arm=None, cam=None, executor=None):
    """Execute a single flow step and log it."""
    action_type = step["action_type"]
    step_name = step["step_name"]
    step_number = step["step_number"]
    c = _cam(cam)

    pre_delay = step.get("pre_delay_ms", 0) or 0
    if pre_delay > 0 and action_type != "PHOTO":
        await asyncio.sleep(pre_delay / 1000.0)

    start_time = time.time()
    result = "ok"
    message = None
    screenshot_b64 = None

    try:
        handler = ACTION_MAP.get(action_type)
        if handler is None:
            logger.warning("Unknown action_type: %s, skipping", action_type)
            return True
        ret = await handler(step, bank_code, station_id, transaction, password, arm=arm, cam=cam, executor=executor)
        if action_type == "PHOTO" and isinstance(ret, str):
            screenshot_b64 = ret
    except Exception as e:
        result = "fail"
        message = str(e)
        logger.error("Step %d (%s) failed: %s", step_number, step_name, e)
        try:
            screenshot_b64 = await _hw(executor, c.capture_base64)
        except Exception as screenshot_err:
            logger.warning("Error screenshot capture failed: %s", screenshot_err)

    duration_ms = int((time.time() - start_time) * 1000)

    post_delay = step.get("post_delay_ms", 0) or 0
    if post_delay > 0:
        await asyncio.sleep(post_delay / 1000.0)

    if action_type not in ("OCR_VERIFY", "CHECK_SCREEN"):
        await database.execute(
            """INSERT INTO transaction_logs 
            (transaction_id, step_number, step_name, action_type, result, duration_ms, screenshot_base64, message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (transaction_id, step_number, step_name, action_type, result, duration_ms, screenshot_b64, message),
        )

    return result == "ok"
