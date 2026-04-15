"""OCR verification - configurable field checking + receipt status support"""
import os
import re
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


def extract_text(frame):
    """Extract all text from image frame (auto-rotates 90 CW first)"""
    frame = rotate_frame(frame)
    reader = get_reader()
    if reader is None:
        return "", frame
    if reader == "tesseract":
        import pytesseract
        text = pytesseract.image_to_string(frame)
        return text, frame
    else:
        results = reader.readtext(frame, detail=0)
        return " ".join(results), frame


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

    Returns (success, ocr_text, screenshot_b64, receipt_result)
    receipt_result: "success"/"review"/"failed"/None
    """
    if frame is None:
        return False, "Frame is None", None, None

    text, rotated_frame = extract_text(frame)
    logger.info("OCR extracted text: %s", text[:200])

    _, buffer = cv2.imencode(".jpg", rotated_frame)
    screenshot_b64 = base64.b64encode(buffer).decode("utf-8")

    text_clean = re.sub(r'\s+', '', text)
    text_digits = re.sub(r'[^0-9]', '', text)
    numbers = extract_numbers(text)
    failures = []

    verify_fields = ocr_config.get("verify_fields", [])

    for field in verify_fields:
        expected = transaction_values.get(field)
        if not expected:
            continue

        if field == "pay_to_account_no":
            found_account = False
            candidates = [expected, expected.lstrip("0")]
            for i in range(len(expected)):
                suffix = expected[i:]
                if len(suffix) >= 6:
                    candidates.append(suffix)
            for candidate in candidates:
                if candidate and (candidate in text_digits or candidate in text_clean):
                    found_account = True
                    break
            if not found_account:
                failures.append("account '%s' not found" % expected)

        elif field == "amount":
            amt_norm = str(float(expected))
            if amt_norm.endswith('.0'):
                amt_norm = amt_norm[:-2]
            found = False
            for num in numbers:
                n = str(float(num)) if '.' in num else num
                if n.endswith('.0'):
                    n = n[:-2]
                if n == amt_norm or num == expected:
                    found = True
                    break
            if not found:
                failures.append("amount '%s' not found (numbers: %s)" % (expected, numbers))

        elif field == "pay_to_account_name":
            name_lower = expected.lower()
            text_lower = text.lower()
            if name_lower not in text_lower and name_lower.replace(" ", "") not in text_clean.lower():
                failures.append("name '%s' not found" % expected)

    receipt_result = None
    receipt_config = ocr_config.get("receipt_status")
    if receipt_config:
        text_lower = text.lower()
        for status_key in ["success", "review", "failed"]:
            keywords = receipt_config.get(status_key, [])
            for kw in keywords:
                if kw.lower() in text_lower:
                    receipt_result = status_key
                    break
            if receipt_result:
                break
        if receipt_result is None:
            failures.append("receipt status not detected (no keyword matched)")

    if failures:
        msg = "OCR FAILED: " + " | ".join(failures) + " | raw: " + text[:300]
        logger.warning("OCR verification FAILED: %s", msg)
        return False, msg, screenshot_b64, receipt_result
    else:
        logger.info("OCR verification PASSED: fields=%s receipt=%s", verify_fields, receipt_result)
        return True, text, screenshot_b64, receipt_result
