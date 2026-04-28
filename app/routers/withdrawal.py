"""API endpoints for withdrawal processing — multi-arm version.

Task assignment: bank_apps.station_id → stations.arm_id → route to correct worker.
"""
import logging
import re
from fastapi import APIRouter, Depends
from pymysql.err import IntegrityError
from app.models import WithdrawalRequest, StandardResponse, HealthResponse, StatusResponse
from app.auth import verify_api_key
from app import database
from app.worker_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()

# Strips ASCII/Unicode whitespace + zero-width formatting chars (U+200B/C/D, U+FEFF).
# Account numbers must be plain digits before they reach the keyboard typer
# and the OCR matcher; PAS sometimes ships values like '000 515 302' or
# '001\u200b 514 964' that would otherwise leak through.
_ACCOUNT_NO_STRIP = re.compile(r'[\s\u200b\u200c\u200d\ufeff]+')


def _sanitize_account_no(value):
    if not value:
        return value
    return _ACCOUNT_NO_STRIP.sub('', str(value))


@router.post("/process-withdrawal", response_model=StandardResponse, dependencies=[Depends(verify_api_key)])
async def process_withdrawal(req: WithdrawalRequest):
    req.pay_from_account_no = _sanitize_account_no(req.pay_from_account_no)
    req.pay_to_account_no = _sanitize_account_no(req.pay_to_account_no)

    if req.pay_from_bank_code == req.pay_to_bank_code and req.pay_from_account_no == req.pay_to_account_no:
        return StandardResponse(status=False, message="Self-transfer rejected: sender and receiver are the same account")

    existing = await database.fetchone(
        "SELECT id FROM transactions WHERE process_id = %s", (req.process_id,)
    )
    if existing:
        return StandardResponse(status=False, message="Duplicate process_id")

    bank_app = await database.fetchone(
        "SELECT ba.id, ba.station_id, s.arm_id FROM bank_apps ba "
        "JOIN stations s ON ba.station_id = s.id "
        "WHERE ba.bank_code = %s AND ba.account_no = %s AND ba.status = 'active'",
        (req.pay_from_bank_code, req.pay_from_account_no),
    )

    if not bank_app:
        try:
            await database.execute(
                """INSERT INTO transactions 
                (process_id, currency_code, amount, pay_from_bank_code, pay_from_account_no,
                 pay_to_bank_code, pay_to_account_no, pay_to_account_name, status, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'failed', 'Bank app not found')""",
                (req.process_id, req.currency_code, req.amount, req.pay_from_bank_code,
                 req.pay_from_account_no, req.pay_to_bank_code, req.pay_to_account_no, req.pay_to_account_name),
            )
        except IntegrityError as e:
            if e.args[0] == 1062:
                return StandardResponse(status=False, message="Duplicate process_id")
            raise
        return StandardResponse(status=False, message="Bank app not found for given bank_code + account_no")

    arm = await database.fetchone(
        "SELECT id, active, status FROM arms WHERE id = %s", (bank_app["arm_id"],)
    )
    if not arm or not arm["active"] or arm["status"] == "offline":
        try:
            await database.execute(
                """INSERT INTO transactions 
                (process_id, currency_code, amount, pay_from_bank_code, pay_from_account_no,
                 pay_to_bank_code, pay_to_account_no, pay_to_account_name,
                 bank_app_id, station_id, status, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'failed', 'Arm offline or inactive')""",
                (req.process_id, req.currency_code, req.amount, req.pay_from_bank_code,
                 req.pay_from_account_no, req.pay_to_bank_code, req.pay_to_account_no, req.pay_to_account_name,
                 bank_app["id"], bank_app["station_id"]),
            )
        except IntegrityError as e:
            if e.args[0] == 1062:
                return StandardResponse(status=False, message="Duplicate process_id")
            raise
        return StandardResponse(status=False, message="Assigned arm is offline or inactive")

    try:
        await database.execute(
            """INSERT INTO transactions 
            (process_id, currency_code, amount, pay_from_bank_code, pay_from_account_no,
             pay_to_bank_code, pay_to_account_no, pay_to_account_name,
             bank_app_id, station_id, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued')""",
            (req.process_id, req.currency_code, req.amount, req.pay_from_bank_code,
             req.pay_from_account_no, req.pay_to_bank_code, req.pay_to_account_no, req.pay_to_account_name,
             bank_app["id"], bank_app["station_id"]),
        )
    except IntegrityError as e:
        if e.args[0] == 1062:
            return StandardResponse(status=False, message="Duplicate process_id")
        raise

    manager.notify_worker(bank_app["arm_id"])

    logger.info("Withdrawal queued: process_id=%d bank=%s station=%d arm=%d",
                req.process_id, req.pay_from_bank_code, bank_app["station_id"], bank_app["arm_id"])

    return StandardResponse(status=True, message="Withdrawal Request Accepted")


@router.get("/status/{process_id}", response_model=StatusResponse, dependencies=[Depends(verify_api_key)])
async def get_status(process_id: int):
    row = await database.fetchone(
        """SELECT process_id, status, error_message, created_at, started_at, finished_at 
        FROM transactions WHERE process_id = %s""",
        (process_id,),
    )
    if not row:
        return StatusResponse(process_id=process_id, status="not_found")
    return StatusResponse(
        process_id=row["process_id"],
        status=row["status"],
        error_message=row["error_message"],
        created_at=str(row["created_at"]) if row["created_at"] else None,
        started_at=str(row["started_at"]) if row["started_at"] else None,
        finished_at=str(row["finished_at"]) if row["finished_at"] else None,
    )


@router.get("/health", response_model=HealthResponse)
async def health_check():
    try:
        result = await database.fetchone("SELECT 1 as ok")
        db_ok = result is not None

        arms = await database.fetchall("SELECT id, name, status FROM arms WHERE active = 1")
        arm_summary = ", ".join("%s:%s" % (a["name"], a["status"]) for a in arms) if arms else "none"

        return HealthResponse(
            status="ok" if db_ok else "error",
            arm_status=arm_summary,
            db_connected=db_ok,
        )
    except Exception as e:
        return HealthResponse(
            status="error",
            arm_status="unknown",
            db_connected=False,
            details=str(e),
        )
