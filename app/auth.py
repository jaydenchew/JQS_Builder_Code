"""API authentication — validates X-Api-Key and X-Tenant-ID headers"""
import logging
from fastapi import Request, HTTPException
from app.config import WA_API_KEY, WA_TENANT_ID

logger = logging.getLogger(__name__)


async def verify_api_key(request: Request):
    """FastAPI dependency: validate API key and tenant ID from request headers"""
    api_key = request.headers.get("X-Api-Key", "")
    tenant_id = request.headers.get("X-Tenant-ID", "")

    if not WA_API_KEY or not WA_TENANT_ID:
        logger.error(
            "WA auth misconfigured: WA_API_KEY or WA_TENANT_ID missing. path=%s",
            request.url.path,
        )
        raise HTTPException(status_code=503, detail="WA API authentication not configured")

    if api_key != WA_API_KEY or tenant_id != WA_TENANT_ID:
        logger.warning("Unauthorized request: ip=%s path=%s", request.client.host, request.url.path)
        raise HTTPException(status_code=401, detail="Unauthorized: invalid API key or tenant ID")
