"""API endpoints for withdrawal processing — multi-arm version.

Task assignment: bank_apps.station_id → stations.arm_id → route to correct worker.
"""
import logging
import re
from fastapi import APIRouter, Depends
from pymysql.err import IntegrityError
from app.models import WithdrawalRequest, StandardResponse, HealthResponse, StatusResponse
from app.auth import verify_api_key
from app import database, maintenance
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


async def _link_retry_chain(new_tx_id, ref_process_id):
    """Link this tx to the stall it retries, identified by PAS via ref_process_id.

    PAS always sends the *original* (first) stall's process_id as ref_process_id,
    no matter how many times it retries. We locate that root transaction, follow
    its superseded_by pointer to the current chain tail, then re-point the tail
    and every member already pointing at it to this new tx. Invariant: every
    superseded member points directly at the current tail, so the whole chain
    collapses onto the latest retry and the deduped view shows only this tx.
    """
    if not ref_process_id:
        return
    root = await database.fetchone(
        "SELECT id, superseded_by FROM transactions WHERE process_id = %s",
        (ref_process_id,))
    if not root:
        return
    tail_id = root["superseded_by"] or root["id"]
    if tail_id == new_tx_id:
        return
    await database.execute(
        "UPDATE transactions SET superseded_by = %s WHERE id = %s OR superseded_by = %s",
        (new_tx_id, tail_id, tail_id))


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
            new_tx_id = await database.execute(
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
        try:
            await _link_retry_chain(new_tx_id, req.ref_process_id)
        except Exception:
            logger.warning("retry chain link failed for tx %d", new_tx_id)
        return StandardResponse(status=False, message="Bank app not found for given bank_code + account_no")

    # Maintenance window: reject WITHOUT writing a transaction row, so the
    # process_id stays free for PAS to resend after the window. Fail-open —
    # any error inside the check lets the withdrawal proceed normally.
    mnt = await maintenance.get_active_window(bank_app["arm_id"])
    if mnt:
        logger.info("Withdrawal rejected (maintenance window): process_id=%d arm=%d",
                    req.process_id, bank_app["arm_id"])
        return StandardResponse(
            status=False,
            message="System under maintenance, please resend after %s (UTC+%d)"
                    % (mnt["end_time"], mnt["tz_offset"]))

    arm = await database.fetchone(
        "SELECT id, active, status FROM arms WHERE id = %s", (bank_app["arm_id"],)
    )
    if not arm or not arm["active"] or arm["status"] == "offline":
        try:
            new_tx_id = await database.execute(
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
        try:
            await _link_retry_chain(new_tx_id, req.ref_process_id)
        except Exception:
            logger.warning("retry chain link failed for tx %d", new_tx_id)
        return StandardResponse(status=False, message="Assigned arm is offline or inactive")

    try:
        new_tx_id = await database.execute(
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

    try:
        await _link_retry_chain(new_tx_id, req.ref_process_id)
    except Exception:
        logger.warning("retry chain link failed for tx %d", new_tx_id)

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
