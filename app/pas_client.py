"""HTTP client for PAS callbacks — reuses a single AsyncClient for connection pooling.

Receipt photos are sent as multipart/form-data files (not base64 JSON).
DB still stores base64 — only the PAS HTTP call converts to file bytes.
Retry: on failure, retries up to 3 times with 5s/15s/30s backoff.
"""
import io
import asyncio
import base64
import httpx
import logging
from app.config import PAS_API_URL, PAS_API_KEY, PAS_TENANT_ID

logger = logging.getLogger(__name__)

_auth_headers = {
    "X-Api-Key": PAS_API_KEY,
    "X-Tenant-ID": PAS_TENANT_ID,
}

_json_headers = {
    **_auth_headers,
    "Content-Type": "application/json",
}

_client = None


def _get_client():
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30)
    return _client


async def close_client():
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


RETRY_DELAYS = [5, 15, 30]


async def callback_result(process_id: int, status: int, transaction_datetime: str, receipt: str = None):
    """Report withdrawal result to PAS with retry.

    When receipt (base64 JPEG) is provided, sends as multipart/form-data file.
    Otherwise sends JSON without receipt.
    Retries up to 3 times on failure with 5s/15s/30s backoff.
    """
    if not PAS_API_URL:
        logger.error("PAS callback skipped: PAS_API_URL not configured (process_id=%d)", process_id)
        return None

    for attempt in range(1 + len(RETRY_DELAYS)):
        result = await _send_callback(process_id, status, transaction_datetime, receipt)
        if result is not None:
            return result
        if attempt < len(RETRY_DELAYS):
            delay = RETRY_DELAYS[attempt]
            logger.warning("PAS callback retry %d/%d for process_id=%d in %ds",
                           attempt + 1, len(RETRY_DELAYS), process_id, delay)
            await asyncio.sleep(delay)

    logger.error("PAS callback FAILED after %d retries: process_id=%d", len(RETRY_DELAYS), process_id)
    return None


async def _send_callback(process_id: int, status: int, transaction_datetime: str, receipt: str = None):
    data_fields = {
        "process_id": str(process_id),
        "status": str(status),
        "transaction_datetime": transaction_datetime,
    }

    try:
        client = _get_client()
        if receipt:
            receipt_bytes = base64.b64decode(receipt)
            files = {"receipt": ("receipt.jpg", io.BytesIO(receipt_bytes), "image/jpeg")}
            resp = await client.post(
                f"{PAS_API_URL}/process-withdrawal",
                data=data_fields,
                files=files,
                headers=_auth_headers,
            )
        else:
            payload = {
                "process_id": process_id,
                "status": status,
                "transaction_datetime": transaction_datetime,
            }
            resp = await client.post(
                f"{PAS_API_URL}/process-withdrawal",
                json=payload,
                headers=_json_headers,
            )
        logger.info("PAS callback: process_id=%d status=%d resp=%d", process_id, status, resp.status_code)
        if resp.status_code < 200 or resp.status_code >= 300:
            logger.error("PAS callback rejected: process_id=%d resp=%d body=%s", process_id, resp.status_code, resp.text[:200])
            return None
        return resp.json()
    except Exception as e:
        logger.error("PAS callback failed: %s", e)
        return None
