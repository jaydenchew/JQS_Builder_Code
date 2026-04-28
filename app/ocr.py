"""OCR verification - configurable field checking + receipt status support"""
import os
import re
import time
import logging
import cv2
import base64
from pathlib import Path

logger = logging.getLogger(__name__)

_reader = None

MODEL_DIR = str(Path(__file__).resolve().parent.parent / "models")


def get_reader():
    global _reader
    if _reader is not None:
        return _reader
    try:
        import easyocr
        model_dir = MODEL_DIR if os.path.isdir(MODEL_DIR) else None
        _reader = easyocr.Reader(["en"], gpu=False, model_storage_directory=model_dir)
        logger.info("OCR engine: EasyOCR (models: %s)", model_dir or "default")
        return _reader
    except ImportError:
        logger.warning("EasyOCR not installed, trying Tesseract")
    try:
        import pytesseract
        from app.config import TESSERACT_CMD
        if TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
        _reader = "tesseract"
        logger.info("OCR engine: Tesseract (%s)", TESSERACT_CMD)
        return _reader
    except ImportError:
        logger.error("No OCR engine available. Install easyocr or pytesseract.")
        return None


def rotate_frame(frame):
    return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)


def _enhance_for_ocr(frame):
    """Enhance image contrast and sharpness for better OCR accuracy.
    Converts to grayscale, applies CLAHE for local contrast, then
    upscales 2x with bicubic interpolation for sharper text edges."""
    import numpy as np
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    upscaled = cv2.resize(enhanced, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return upscaled


def extract_text(frame):
    """Extract all text from image frame (auto-rotates 90 CW first)"""
    frame = rotate_frame(frame)
    return _ocr_frame(frame), frame


def _ocr_frame(rotated_frame):
    """Run OCR on an already-rotated frame. Returns text string."""
    reader = get_reader()
    if reader is None:
        return ""
    if reader == "tesseract":
        import pytesseract
        return pytesseract.image_to_string(rotated_frame)
    else:
        results = reader.readtext(rotated_frame, detail=0)
        return " ".join(results)


def _quick_match(text, field_name, expected):
    """Quick check if OCR text matches expected value for a field."""
    if field_name == "pay_to_account_no":
        text_digits = re.sub(r'[^0-9]', '', text)
        text_clean = re.sub(r'\s+', '', text)
        # Normalize expected to digits-only so PAS-supplied formats like
        # '000 515 302' or '001\u200b 514 964' still match against pure-digit OCR text.
        expected_digits = re.sub(r'[^0-9]', '', str(expected))
        if not expected_digits:
            return False
        candidates = [expected_digits, expected_digits.lstrip("0")]
        for i in range(len(expected_digits)):
            suffix = expected_digits[i:]
            if len(suffix) >= 6:
                candidates.append(suffix)
        return any(c and (c in text_digits or c in text_clean) for c in candidates)
    elif field_name == "amount":
        numbers = extract_numbers(text)
        amt_norm = str(float(expected))
        if amt_norm.endswith('.0'):
            amt_norm = amt_norm[:-2]
        for num in numbers:
            n = str(float(num)) if '.' in num else num
            if n.endswith('.0'):
                n = n[:-2]
            if n == amt_norm or num == expected:
                return True
        return False
    return False


METHOD_NAMES = [
    "inverted",
    "adapt_inv",
    "otsu_inv",
    "direct",
    "adapt_direct",
    "otsu_direct",
]


def _ocr_field(cropped_frame, field_name, expected=None):
    """OCR a single cropped field region with targeted engine.

    Returns dict: {"text": str, "method": str, "engine": str, "attempts": int, "latency_ms": int}

    Numeric fields (account, amount) → Tesseract + digit whitelist + multi-preprocessing (6 methods × 2 PSM).
    If expected is provided, continues trying methods until a matching result is found.
    Text fields (name, receipt_status) → EasyOCR.
    All fields get CLAHE + 3x upscale preprocessing.
    """
    t0 = time.time()
    gray = cv2.cvtColor(cropped_frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    upscaled = cv2.resize(enhanced, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

    def _done(text, method, engine, attempts):
        return {
            "text": text or "",
            "method": method,
            "engine": engine,
            "attempts": attempts,
            "latency_ms": int((time.time() - t0) * 1000),
        }

    if field_name in ("pay_to_account_no", "amount"):
        import pytesseract
        from app.config import TESSERACT_CMD
        if TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

        whitelist = "0123456789"
        if field_name == "amount":
            whitelist += ".,$"

        inverted = cv2.bitwise_not(upscaled)
        blurred = cv2.GaussianBlur(upscaled, (3, 3), 0)
        blurred_inv = cv2.GaussianBlur(inverted, (3, 3), 0)
        methods = [
            inverted,
            cv2.adaptiveThreshold(blurred_inv, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5),
            cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
            upscaled,
            cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5),
            cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        ]
        best_text = None
        best_method = None
        attempts = 0
        for idx, proc in enumerate(methods):
            bordered = cv2.copyMakeBorder(proc, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            for psm in [6, 7]:
                attempts += 1
                method_name = "%s_psm%d" % (METHOD_NAMES[idx], psm)
                text = pytesseract.image_to_string(bordered,
                    config="--psm %d -c tessedit_char_whitelist=%s" % (psm, whitelist)).strip()
                if text and any(c.isdigit() for c in text):
                    if expected is None or _quick_match(text, field_name, expected):
                        return _done(text, method_name, "tesseract", attempts)
                    if best_text is None:
                        best_text = text
                        best_method = method_name

        # Tesseract didn't match — try EasyOCR fallback
        reader = get_reader()
        last_easy_text = None
        if reader and reader != "tesseract":
            upscaled_4x = cv2.resize(enhanced, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            attempts += 1
            results = reader.readtext(upscaled_4x, detail=0)
            text = " ".join(results)
            last_easy_text = text
            if text and (expected is None or _quick_match(text, field_name, expected)):
                return _done(text, "easyocr_4x_direct", "easyocr", attempts)
            inverted_4x = cv2.resize(cv2.bitwise_not(enhanced), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            attempts += 1
            results = reader.readtext(inverted_4x, detail=0)
            text = " ".join(results)
            last_easy_text = text or last_easy_text
            if text and (expected is None or _quick_match(text, field_name, expected)):
                return _done(text, "easyocr_4x_inverted", "easyocr", attempts)

        # Nothing matched — return best Tesseract result or last EasyOCR result for logging
        if best_text:
            return _done(best_text, best_method or "best_tesseract", "tesseract", attempts)
        return _done(last_easy_text or "", "none", "easyocr" if last_easy_text else "tesseract", attempts)

    else:
        reader = get_reader()
        if reader is None:
            return _done("", "no_engine", "none", 0)
        if reader == "tesseract":
            import pytesseract
            text = pytesseract.image_to_string(upscaled).strip()
            return _done(text, "direct", "tesseract", 1)
        results = reader.readtext(upscaled, detail=0)
        return _done(" ".join(results), "direct", "easyocr", 1)


def extract_numbers(text):
    return re.findall(r'[\d]+\.?[\d]*', text)


def verify_transfer_from_frame(frame, expected_account: str, expected_amount: str):
    """Legacy: verify account + amount. Used when no OCR config is provided."""
    return verify_configurable(frame, {
        "verify_fields": ["pay_to_account_no", "amount"],
    }, {"pay_to_account_no": expected_account, "amount": expected_amount})


def verify_configurable(frame, ocr_config: dict, transaction_values: dict):
    """Configurable OCR verification.

    ocr_config: {
        "verify_fields": ["pay_to_account_no", "amount", "pay_to_account_name"],
        "receipt_status": {
            "success": ["Success", "Successful"],
            "review": ["In Review", "Pending"],
            "failed": ["Failed", "Unsuccessful"]
        }  // or null
    }
    transaction_values: {
        "pay_to_account_no": "8606194149",
        "amount": "1.23",
        "pay_to_account_name": "John Doe"
    }

    Returns (success, ocr_text, screenshot_b64, receipt_result, ocr_meta)
    receipt_result: "success"/"review"/"failed"/None
    ocr_meta: {"fields": {<field>: {method, engine, attempts, latency_ms}}, "total_latency_ms": int}
    """
    t_total = time.time()
    if frame is None:
        return False, "Frame is None", None, None, None

    rotated_frame = rotate_frame(frame)
    h, w = rotated_frame.shape[:2]

    _, buffer = cv2.imencode(".jpg", rotated_frame)
    screenshot_b64 = base64.b64encode(buffer).decode("utf-8")

    field_rois = ocr_config.get("field_rois")
    verify_fields = ocr_config.get("verify_fields", [])
    failures = []
    all_ocr_texts = {}
    ocr_meta_fields = {}

    def _crop_roi(roi_dict):
        y1 = int(h * roi_dict.get("top_percent", 0) / 100)
        y2 = int(h * roi_dict.get("bottom_percent", 100) / 100)
        x1 = int(w * roi_dict.get("left_percent", 0) / 100)
        x2 = int(w * roi_dict.get("right_percent", 100) / 100)
        if y1 >= y2 or x1 >= x2:
            logger.warning("Invalid ROI: top=%d bottom=%d left=%d right=%d", y1, y2, x1, x2)
            return None
        return rotated_frame[y1:y2, x1:x2]

    def _get_text_for_field(field, expected=None):
        """Get OCR text for a field: field_rois > single roi > fullscreen.
        Also populates ocr_meta_fields[field] with engine/method/attempts/latency."""
        if field_rois and field in field_rois:
            roi_cfg = field_rois[field]
            cropped = _crop_roi(roi_cfg)
            if cropped is None:
                return None
            logger.info("Field ROI [%s]: %s -> crop %dx%d", field, roi_cfg, cropped.shape[1], cropped.shape[0])
            result = _ocr_field(cropped, field, expected=expected)
            ocr_meta_fields[field] = {
                "method": result["method"],
                "engine": result["engine"],
                "attempts": result["attempts"],
                "latency_ms": result["latency_ms"],
            }
            text = result["text"]
            logger.info("Field OCR [%s]: '%s' (method=%s attempts=%d %dms)",
                        field, text[:100], result["method"], result["attempts"], result["latency_ms"])
            return text
        return None

    # Fallback text (single ROI or fullscreen) — computed lazily
    _fallback_text = None
    def _get_fallback_text():
        nonlocal _fallback_text
        if _fallback_text is not None:
            return _fallback_text
        roi = ocr_config.get("roi")
        if roi:
            cropped = _crop_roi(roi)
            if cropped is not None:
                enhanced = _enhance_for_ocr(cropped)
                _fallback_text = _ocr_frame(enhanced)
            else:
                _fallback_text = _ocr_frame(rotated_frame)
        else:
            _fallback_text = _ocr_frame(rotated_frame)
        logger.info("OCR extracted text: %s", _fallback_text[:200])
        return _fallback_text

    def _match_account(text, expected):
        text_clean = re.sub(r'\s+', '', text)
        text_digits = re.sub(r'[^0-9]', '', text)
        # Normalize expected to digits-only — PAS-supplied account numbers may
        # contain spaces, dashes or zero-width characters (U+200B etc).
        expected_digits = re.sub(r'[^0-9]', '', str(expected))
        if not expected_digits:
            return False
        candidates = [expected_digits, expected_digits.lstrip("0")]
        for i in range(len(expected_digits)):
            suffix = expected_digits[i:]
            if len(suffix) >= 6:
                candidates.append(suffix)
        for c in candidates:
            if c and (c in text_digits or c in text_clean):
                return True
        return False

    def _match_amount(text, expected):
        numbers = extract_numbers(text)
        amt_norm = str(float(expected))
        if amt_norm.endswith('.0'):
            amt_norm = amt_norm[:-2]
        for num in numbers:
            n = str(float(num)) if '.' in num else num
            if n.endswith('.0'):
                n = n[:-2]
            if n == amt_norm or num == expected:
                return True
        return False

    def _match_name(text, expected):
        name_lower = expected.lower()
        text_lower = text.lower()
        text_clean = re.sub(r'\s+', '', text).lower()
        return name_lower in text_lower or name_lower.replace(" ", "") in text_clean

    for field in verify_fields:
        expected = transaction_values.get(field)
        if not expected:
            continue

        field_text = _get_text_for_field(field, expected=str(expected))
        text = field_text if field_text is not None else _get_fallback_text()
        all_ocr_texts[field] = text

        if field == "pay_to_account_no":
            if not _match_account(text, expected):
                failures.append("account '%s' not found" % expected)
        elif field == "amount":
            if not _match_amount(text, expected):
                numbers = extract_numbers(text)
                failures.append("amount '%s' not found (numbers: %s)" % (expected, numbers))
        elif field == "pay_to_account_name":
            if not _match_name(text, expected):
                failures.append("name '%s' not found" % expected)

    receipt_result = None
    receipt_config = ocr_config.get("receipt_status")
    if receipt_config:
        receipt_text = None
        if field_rois and "receipt_status" in field_rois:
            cropped = _crop_roi(field_rois["receipt_status"])
            if cropped is None:
                cropped = rotated_frame
            result = _ocr_field(cropped, "receipt_status")
            ocr_meta_fields["receipt_status"] = {
                "method": result["method"],
                "engine": result["engine"],
                "attempts": result["attempts"],
                "latency_ms": result["latency_ms"],
            }
            receipt_text = result["text"]
            logger.info("Field OCR [receipt_status]: '%s' (method=%s %dms)",
                        receipt_text[:100], result["method"], result["latency_ms"])
        else:
            receipt_text = _get_fallback_text()

        text_lower = receipt_text.lower()
        for status_key in ["failed", "review", "success"]:
            keywords = receipt_config.get(status_key, [])
            for kw in keywords:
                if kw.lower() in text_lower:
                    receipt_result = status_key
                    break
            if receipt_result:
                break
        if receipt_result is None:
            failures.append("receipt status not detected (no keyword matched)")

    ocr_summary = " | ".join("%s='%s'" % (k, v[:80]) for k, v in all_ocr_texts.items()) if all_ocr_texts else _get_fallback_text()[:300]

    ocr_meta = {
        "fields": ocr_meta_fields,
        "total_latency_ms": int((time.time() - t_total) * 1000),
    }

    if failures:
        msg = "OCR FAILED: " + " | ".join(failures) + " | raw: " + ocr_summary
        logger.warning("OCR verification FAILED: %s", msg)
        return False, msg, screenshot_b64, receipt_result, ocr_meta
    else:
        logger.info("OCR verification PASSED: fields=%s receipt=%s total=%dms",
                    verify_fields, receipt_result, ocr_meta["total_latency_ms"])
        return True, ocr_summary, screenshot_b64, receipt_result, ocr_meta
