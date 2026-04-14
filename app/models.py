"""Pydantic request/response models"""
from pydantic import BaseModel, Field
from typing import Optional


# === PAS -> WA ===

class WithdrawalRequest(BaseModel):
    process_id: int
    currency_code: str
    amount: float = Field(gt=0, description="Transfer amount, must be positive")
    pay_from_bank_code: str
    pay_from_account_no: str
    pay_to_bank_code: str
    pay_to_account_no: str
    pay_to_account_name: str


# === WA Internal ===

class HealthResponse(BaseModel):
    status: str  # "ok" or "error"
    arm_status: str
    db_connected: bool
    details: Optional[str] = None


class StatusResponse(BaseModel):
    process_id: int
    status: str
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class StandardResponse(BaseModel):
    status: bool
    message: str
    data: Optional[dict] = None
