"""WA Unified System — Builder UI + Withdrawal Automation API + Multi-Arm Workers
Single FastAPI process, port 9000"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.database import get_pool, close_pool
from app.routers import (
    stations, banks, flows, coordinates,
    calibration_router, stream, recorder,
    opencv_router, withdrawal, monitor,
)
from app import camera, arm_client, config, pas_client
from app.worker_manager import manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def validate_config():
    missing = []
    if not config.DB_PASSWORD:
        missing.append("DB_PASSWORD")
    if not config.DB_NAME:
        missing.append("DB_NAME")
    if missing:
        raise RuntimeError("Missing required .env variables: %s" % ", ".join(missing))
    if not config.PAS_API_URL:
        logger.warning("PAS_API_URL not set — PAS callbacks disabled")
    if not config.WA_API_KEY or not config.WA_TENANT_ID:
        logger.warning("WA_API_KEY/WA_TENANT_ID missing — protected endpoints will return 503")


@asynccontextmanager
async def lifespan(app):
    validate_config()
    await get_pool()
    logger.info("Database connected")

    stale = await database.fetchall(
        "SELECT id, process_id FROM transactions WHERE status = 'running'")
    if stale:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for t in stale:
            await database.execute(
                "UPDATE transactions SET status = 'stall', error_message = 'Service restarted while running', finished_at = NOW() WHERE id = %s",
                (t["id"],))
            await pas_client.callback_result(t["process_id"], 4, now)
            logger.warning("Recovered stale transaction: process_id=%d → stall", t["process_id"])
        logger.info("Recovered %d stale running transactions", len(stale))

    await manager.start_all()
    logger.info("WA Unified System started — port 9000")

    yield

    await manager.stop_all()

    if arm_client.is_connected():
        try:
            arm_client.reset_to_origin()
            arm_client.close_port()
        except Exception:
            pass
    camera.camera_close()
    await pas_client.close_client()
    await close_pool()
    logger.info("WA Unified System stopped")


app = FastAPI(
    title="WA Unified System",
    description="Builder UI + Withdrawal Automation + Multi-Arm Workers",
    version="2.0.0",
    lifespan=lifespan,
)

# --- Builder UI routes ---
app.include_router(stations.router)
app.include_router(banks.router)
app.include_router(flows.router)
app.include_router(coordinates.router)
app.include_router(calibration_router.router)
app.include_router(stream.router)
app.include_router(recorder.router)
app.include_router(opencv_router.router)

# --- WA Execution API ---
app.include_router(withdrawal.router)

# --- Monitor API + WebSocket ---
app.include_router(monitor.router)

# --- Static files ---
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/recorder")
async def recorder_page():
    return FileResponse("static/recorder.html")


@app.get("/transactions")
async def transactions_page():
    return FileResponse("static/transactions.html")


@app.get("/settings")
async def settings_page():
    return FileResponse("static/settings.html")
