"""Monitoring API + WebSocket for real-time dashboard"""
import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app import database
from app.worker_manager import manager

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
    """Today's transaction statistics."""
    rows = await database.fetchall(
        """SELECT status, COUNT(*) as cnt FROM transactions 
        WHERE DATE(created_at) = CURDATE()
        GROUP BY status"""
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


@router.post("/pause/{arm_id}")
async def pause_arm(arm_id: int):
    ok = manager.pause(arm_id)
    return {"success": ok}


@router.post("/resume/{arm_id}")
async def resume_arm(arm_id: int):
    ok = await manager.resume(arm_id)
    if ok:
        await database.execute("UPDATE arms SET status = 'idle', active = 1 WHERE id = %s", (arm_id,))
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
        worker.arm_client.reset_to_origin()
        worker.arm_client.close_port()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


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
        where.append("t.created_at >= %s")
        params.append(date_from + " 00:00:00")
    if date_to:
        where.append("t.created_at <= %s")
        params.append(date_to + " 23:59:59")

    where_sql = " AND ".join(where) if where else "1=1"
    rows = await database.fetchall(
        "SELECT t.id, t.process_id, t.pay_from_bank_code, t.pay_to_bank_code, t.amount, t.status, "
        "t.created_at, t.started_at, t.finished_at, t.error_message, t.station_id, "
        "s.arm_id, a.name as arm_name "
        "FROM transactions t "
        "LEFT JOIN stations s ON t.station_id = s.id "
        "LEFT JOIN arms a ON s.arm_id = a.id "
        "WHERE " + where_sql + " ORDER BY t.created_at DESC LIMIT %s OFFSET %s",
        (*params, limit, offset)
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
            db_arms = await database.fetchall("SELECT id, name, com_port, camera_id, active, status FROM arms ORDER BY id")
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
