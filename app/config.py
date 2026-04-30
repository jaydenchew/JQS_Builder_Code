"""Unified configuration — merged from Builder + JQS"""
import os
from dotenv import load_dotenv

load_dotenv()

# Database (single unified DB)
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3308"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "wa_db")

# Arm defaults (per-arm values come from DB, these are fallbacks)
ARM_SERVICE_URL = os.getenv("ARM_SERVICE_URL", "http://127.0.0.1:8082/MyWcfService/getstring")
ARM_COM_PORT = os.getenv("ARM_COM_PORT", "COM6")
ARM_Z_DOWN = int(os.getenv("ARM_Z_DOWN", "10"))
ARM_MOVE_DELAY = float(os.getenv("ARM_MOVE_DELAY", "0.3"))
ARM_PRESS_DELAY = float(os.getenv("ARM_PRESS_DELAY", "0.15"))
ARM_DIGIT_DELAY = float(os.getenv("ARM_DIGIT_DELAY", "0.5"))

# Camera defaults
CAMERA_ID = int(os.getenv("CAMERA_ID", "0"))
CAMERA_WARMUP = int(os.getenv("CAMERA_WARMUP", "2"))

# PAS (WA -> PAS callbacks)
PAS_API_URL = os.getenv("PAS_API_URL", "")
PAS_API_KEY = os.getenv("PAS_API_KEY", "")
PAS_TENANT_ID = os.getenv("PAS_TENANT_ID", "")

# WA API Auth (PAS -> WA requests)
WA_API_KEY = os.getenv("WA_API_KEY", "")
WA_TENANT_ID = os.getenv("WA_TENANT_ID", "")

# Tesseract OCR (for random PIN keypad)
TESSERACT_CMD = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")

# OCR verification behaviour when OCR engine is unavailable
# true (default): raise RuntimeError → task fails, arm pauses (safe)
# false: skip verification and continue (useful for environments without OCR)
OCR_REQUIRED = os.getenv("OCR_REQUIRED", "true").lower() == "true"
