"""Monitoring API + WebSocket for real-time dashboard"""
import asyncio
import base64
import json
import logging
import subprocess
import time
from datetime import datetime, timezone, timedelta
import cv2
import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app import database
from app.camera import Camera
from app.worker_manager import manager
from app.config import ARM_SERVICE_URL

_start_time = time.time()

# Display / business timezone. DB stores everything in UTC; user-facing date
# filters and "today" boundaries are anchored to this offset (UTC+7, Indochina).
DISPLAY_TZ = timezone(timedelta(hours=7))

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.get("/status")
async def get_all_status():
    """Get status of all arm workers."""
    return manager.get_all_status()


@router.get("/queue")
async def get_queue_status():
    """Get count of queued/running tasks."""
    queued = await database.fetchone("SELECT COUNT(*) as cnt FROM transactions WHERE status = 'queued'")
    running = await database.fetchone("SELECT COUNT(*) as cnt FROM transactions WHERE status = 'running'")
    return {"queued": queued["cnt"], "running": running["cnt"]}


@router.get("/stats/today")
async def get_today_stats():
    """Today's transaction statistics, where 'today' is the DISPLAY_TZ day."""
    today_local = datetime.now(DISPLAY_TZ).date()
    start_local = datetime.combine(today_local, datetime.min.time(), tzinfo=DISPLAY_TZ)
    end_local = datetime.combine(today_local, datetime.max.time(), tzinfo=DISPLAY_TZ)
    start_utc = start_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    end_utc = end_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    rows = await database.fetchall(
        "SELECT status, COUNT(*) as cnt FROM transactions "
        "WHERE created_at >= %s AND created_at <= %s "
        "GROUP BY status",
        (start_utc, end_utc),
    )
    stats = {r["status"]: r["cnt"] for r in rows}
    return {
        "success": stats.get("success", 0),
        "failed": stats.get("failed", 0),
        "stall": stats.get("stall", 0),
        "queued": stats.get("queued", 0),
        "running": stats.get("running", 0),
        "total": sum(stats.values()),
    }


@router.get("/services")
async def get_service_status():
    """Check status of all dependent services."""
    result = {}

    # MySQL
    try:
        row = await database.fetchone("SELECT 1 as ok")
        result["mysql"] = {"online": row is not None, "detail": "Connected"}
    except Exception as e:
        result["mysql"] = {"online": False, "detail": str(e)[:100]}

    # Arm WCF Service
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(ARM_SERVICE_URL + "?duankou=COM0&hco=0&daima=0")
            result["arm_wcf"] = {"online": True, "detail": "HTTP %d" % resp.status_code}
    except Exception:
        result["arm_wcf"] = {"online": False, "detail": "Not reachable"}

    # Cloudflare Tunnel
    try:
        proc = await asyncio.get_event_loop().run_in_executor(
            None, lambda: subprocess.run(
                ["sc.exe", "query", "CF-Tunnel"],
                capture_output=True, text=True, timeout=3))
        running = "RUNNING" in proc.stdout
        result["cloudflare_tunnel"] = {"online": running, "detail": "Running" if running else "Stopped"}
    except Exception:
        result["cloudflare_tunnel"] = {"online": False, "detail": "Service not found"}

    # WA Service (self)
    uptime_s = int(time.time() - _start_time)
    hours, remainder = divmod(uptime_s, 3600)
    minutes = remainder // 60
    result["wa_service"] = {"online": True, "detail": "%dh %dm" % (hours, minutes)}

    return result


@router.post("/pause/{arm_id}")
async def pause_arm(arm_id: int):
    ok = manager.pause(arm_id)
    return {"success": ok}


@router.post("/resume/{arm_id}")
async def resume_arm(arm_id: int):
    ok = await manager.resume(arm_id)
    if ok:
        await database.execute(
            "UPDATE arms SET active = 1, status = 'idle', stall_reason = NULL, stall_details = NULL WHERE id = %s",
            (arm_id,))
    return {"success": ok}


@router.post("/offline/{arm_id}")
async def set_offline(arm_id: int):
    await manager.set_offline(arm_id)
    return {"success": True}


@router.post("/reset/{arm_id}")
async def reset_arm(arm_id: int):
    """Remote reset: move arm to origin and close port."""
    worker = manager.get_worker(arm_id)
    if not worker:
        return {"success": False, "error": "Worker not found"}
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(worker._executor, worker.arm_client.reset_to_origin)
        await loop.run_in_executor(worker._executor, worker.arm_client.close_port)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _safe_states_for_camera_op(worker_status: str) -> bool:
    """Camera verify/swap is forbidden ONLY when the worker is actively
    processing a task (busy). Idle workers are safe: capture_fresh just
    briefly contends on the per-arm camera lock; restart_worker on an idle
    worker is equivalent to a quick stop+start and does not lose queued
    tasks (they stay status='queued' and are picked up after restart)."""
    return worker_status != "busy"


def _capture_one_frame_blocking(camera_id: int) -> str | None:
    """Capture one rotated JPEG (base64) from camera_id, going through the
    Camera class so the global Camera._init_lock + _active_instance exclusive
    model is honored. Without this, a direct cv2.VideoCapture call could race
    with another worker's camera operation on Windows DSHOW.

    Used only when the arm has no live worker (worker is None). Blocks ~0.5s
    on DSHOW init — caller must run in executor. Returns None on failure."""
    cam = Camera(camera_id=camera_id)
    frame = cam.capture_fresh()
    if frame is None:
        return None
    frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        return None
    return base64.b64encode(buf).decode("utf-8")


@router.get("/arms/{arm_id}/camera-preview")
async def camera_preview(arm_id: int):
    """Grab one fresh frame from the arm's currently bound camera.

    Only allowed when worker is paused/offline (avoid stealing camera from a
    running task). When worker is paused, asks the worker's Camera instance to
    capture_fresh (its lock prevents conflict with worker's own captures).
    When worker is offline (not in manager.workers), opens camera_id directly
    via a temporary DSHOW VideoCapture — same approach as scan-cameras.
    """
    arm = await database.fetchone("SELECT id, camera_id FROM arms WHERE id = %s", (arm_id,))
    if not arm:
        return {"success": False, "error": "Arm not found"}

    worker = manager.get_worker(arm_id)
    worker_status = worker.get_status() if worker else "no_worker"
    if not _safe_states_for_camera_op(worker_status):
        return {"success": False,
                "error": "Worker is %s. Pause arm first to safely preview camera." % worker_status}

    loop = asyncio.get_event_loop()
    if worker is not None:
        frame = await loop.run_in_executor(None, worker.camera.capture_fresh)
        if frame is None:
            return {"success": False, "error": "Camera %d capture failed" % arm["camera_id"]}
        rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        ok, buf = cv2.imencode(".jpg", rotated, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            return {"success": False, "error": "JPEG encode failed"}
        b64 = base64.b64encode(buf).decode("utf-8")
    else:
        b64 = await loop.run_in_executor(None, _capture_one_frame_blocking, arm["camera_id"])
        if b64 is None:
            return {"success": False, "error": "Camera %d not available" % arm["camera_id"]}

    return {"success": True, "image": b64, "camera_id": arm["camera_id"]}


@router.post("/arms/swap-camera")
async def swap_camera(data: dict):
    """Atomically swap camera_id between two arms and restart both workers.

    Both arms must be paused/offline (or have no worker). Refuses on idle/busy
    to avoid mid-task camera reassignment. Restart picks up the new camera_id
    on the next loop iteration without a service restart.
    """
    arm_id_a = data.get("arm_id_a")
    arm_id_b = data.get("arm_id_b")
    if not arm_id_a or not arm_id_b or arm_id_a == arm_id_b:
        return {"success": False, "error": "Provide two distinct arm_id_a and arm_id_b"}

    rows = await database.fetchall(
        "SELECT id, name, camera_id, active FROM arms WHERE id IN (%s, %s)",
        (arm_id_a, arm_id_b))
    if len(rows) != 2:
        return {"success": False, "error": "One or both arms not found"}
    by_id = {r["id"]: r for r in rows}
    a, b = by_id[arm_id_a], by_id[arm_id_b]

    for arm in (a, b):
        worker = manager.get_worker(arm["id"])
        status = worker.get_status() if worker else "no_worker"
        if not _safe_states_for_camera_op(status):
            return {"success": False,
                    "error": "%s is %s — pause both arms first" % (arm["name"], status)}

    new_a, new_b = b["camera_id"], a["camera_id"]
    await database.execute(
        "UPDATE arms SET camera_id = CASE id WHEN %s THEN %s WHEN %s THEN %s END "
        "WHERE id IN (%s, %s)",
        (a["id"], new_a, b["id"], new_b, a["id"], b["id"])
    )
    logger.warning("Camera swap: %s camera %d->%d, %s camera %d->%d",
                   a["name"], a["camera_id"], new_a, b["name"], b["camera_id"], new_b)

    if a["active"]:
        await manager.restart_worker(a["id"])
    if b["active"]:
        await manager.restart_worker(b["id"])

    return {"success": True,
            "swapped": [
                {"arm_id": a["id"], "name": a["name"], "camera_id": new_a},
                {"arm_id": b["id"], "name": b["name"], "camera_id": new_b},
            ]}


@router.get("/transactions")
async def list_transactions(status: str = None, bank: str = None, to_bank: str = None,
                            arm_id: int = None,
                            date_from: str = None, date_to: str = None,
                            limit: int = 50, offset: int = 0):
    """List transactions with optional filters: status, bank, to_bank, arm_id, date range."""
    where = []
    params = []
    if status:
        where.append("t.status = %s")
        params.append(status)
    if bank:
        where.append("t.pay_from_bank_code = %s")
        params.append(bank)
    if to_bank:
        where.append("t.pay_to_bank_code = %s")
        params.append(to_bank)
    if arm_id:
        where.append("s.arm_id = %s")
        params.append(arm_id)
    if date_from:
        # date_from is the DISPLAY_TZ calendar date; convert its 00:00 boundary to UTC.
        dt_utc = (
            datetime.strptime(date_from, "%Y-%m-%d")
            .replace(hour=0, minute=0, second=0, tzinfo=DISPLAY_TZ)
            .astimezone(timezone.utc)
            .strftime("%Y-%m-%d %H:%M:%S")
        )
        where.append("t.created_at >= %s")
        params.append(dt_utc)
    if date_to:
        # date_to inclusive end-of-day in DISPLAY_TZ, converted to UTC.
        dt_utc = (
            datetime.strptime(date_to, "%Y-%m-%d")
            .replace(hour=23, minute=59, second=59, tzinfo=DISPLAY_TZ)
            .astimezone(timezone.utc)
            .strftime("%Y-%m-%d %H:%M:%S")
        )
        where.append("t.created_at <= %s")
        params.append(dt_utc)

    where_sql = " AND ".join(where) if where else "1=1"
    actual_limit = min(limit, 5000) if limit > 0 else 5000
    rows = await database.fetchall(
        "SELECT t.id, t.process_id, t.pay_from_bank_code, t.pay_to_bank_code, t.amount, t.status, "
        "t.created_at, t.started_at, t.finished_at, t.error_message, t.station_id, "
        "s.arm_id, a.name as arm_name "
        "FROM transactions t "
        "LEFT JOIN stations s ON t.station_id = s.id "
        "LEFT JOIN arms a ON s.arm_id = a.id "
        "WHERE " + where_sql + " ORDER BY t.created_at DESC LIMIT %s OFFSET %s",
        (*params, actual_limit, offset)
    )
    for r in rows:
        for k in ("created_at", "started_at", "finished_at"):
            if r.get(k):
                r[k] = str(r[k])
    return rows


@router.get("/transactions/{transaction_id}")
async def get_transaction_detail(transaction_id: int):
    """Get full transaction detail."""
    tx = await database.fetchone("SELECT * FROM transactions WHERE id = %s", (transaction_id,))
    if not tx:
        return {"error": "Not found"}
    for k in ("created_at", "started_at", "finished_at", "callback_sent_at"):
        if tx.get(k):
            tx[k] = str(tx[k])
    return tx


@router.get("/transactions/{transaction_id}/logs")
async def get_transaction_logs(transaction_id: int):
    """Get step-by-step logs for a transaction."""
    logs = await database.fetchall(
        "SELECT id, step_number, step_name, action_type, result, duration_ms, ocr_text, expected_value, message, created_at, "
        "(screenshot_base64 IS NOT NULL) as has_screenshot "
        "FROM transaction_logs WHERE transaction_id = %s ORDER BY step_number",
        (transaction_id,)
    )
    for l in logs:
        if l.get("created_at"):
            l["created_at"] = str(l["created_at"])
    return logs


@router.get("/transactions/{transaction_id}/logs/{log_id}/screenshot")
async def get_log_screenshot(transaction_id: int, log_id: int):
    """Get screenshot for a specific log entry."""
    row = await database.fetchone(
        "SELECT screenshot_base64 FROM transaction_logs WHERE id = %s AND transaction_id = %s",
        (log_id, transaction_id)
    )
    if not row or not row["screenshot_base64"]:
        return {"error": "No screenshot"}
    return {"screenshot": row["screenshot_base64"]}



@router.get("/logs/{arm_id}")
async def get_arm_logs(arm_id: int, limit: int = 200):
    """Get recent logs for an arm worker."""
    worker = manager.get_worker(arm_id)
    if not worker:
        return {"logs": [], "error": "Worker not running for arm %d" % arm_id}
    return {"logs": worker.get_logs(limit)}


@router.get("/logs")
async def get_all_logs(limit: int = 100):
    """Get merged recent logs from all workers."""
    all_logs = []
    for arm_id, worker in manager.workers.items():
        for log in worker.get_logs(limit):
            log_copy = dict(log)
            log_copy["arm_id"] = arm_id
            log_copy["arm_name"] = worker.name
            all_logs.append(log_copy)
    all_logs.sort(key=lambda x: x["ts"])
    return {"logs": all_logs[-limit:]}


@router.websocket("/logs/ws")
async def websocket_logs(ws: WebSocket, arm_id: int = None):
    """WebSocket: streams new log entries in real-time.
    arm_id=None means all arms, arm_id=N means specific arm only."""
    await ws.accept()
    try:
        while True:
            logs = []
            if arm_id is not None:
                worker = manager.get_worker(arm_id)
                if worker:
                    for log in worker.drain_new_logs():
                        log["arm_name"] = worker.name
                        logs.append(log)
            else:
                for wid, worker in manager.workers.items():
                    for log in worker.drain_new_logs():
                        log["arm_id"] = wid
                        log["arm_name"] = worker.name
                        logs.append(log)

            if logs:
                await ws.send_text(json.dumps(logs, default=str))
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("Log WebSocket error: %s", e)
        try:
            await ws.send_text(json.dumps({"error": str(e)}))
        except Exception:
            pass


@router.websocket("/ws")
async def websocket_monitor(ws: WebSocket):
    """WebSocket: pushes merged worker + DB arm status every 2 seconds."""
    await ws.accept()
    try:
        while True:
            worker_status = manager.get_all_status()
            db_arms = await database.fetchall(
                "SELECT id, name, com_port, camera_id, active, status, stall_reason, stall_details FROM arms ORDER BY id")
            queue = await database.fetchone("SELECT COUNT(*) as cnt FROM transactions WHERE status = 'queued'")

            arms = []
            for arm in db_arms:
                info = worker_status.get(arm["id"])
                arms.append({
                    "arm_id": arm["id"],
                    "name": arm["name"],
                    "com_port": arm["com_port"],
                    "camera_id": arm["camera_id"],
                    "active": bool(arm["active"]),
                    "db_status": arm["status"],
                    "worker_status": info["status"] if info else "no_worker",
                    "current_task": info["current_task"] if info else None,
                    "current_step": info["current_step"] if info else None,
                    "task_count": info["task_count"] if info else 0,
                    "last_error": info["last_error"] if info else None,
                    "stall_reason": info.get("stall_reason") if info else arm.get("stall_reason"),
                    "stall_details": arm.get("stall_details"),
                })

            payload = {
                "arms": arms,
                "queued": queue["cnt"] if queue else 0,
            }
            await ws.send_text(json.dumps(payload, default=str))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("Monitor WebSocket error: %s", e)
        try:
            await ws.send_text(json.dumps({"error": str(e)}))
        except Exception:
            pass
