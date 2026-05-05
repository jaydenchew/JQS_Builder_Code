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
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from app import database
from app.auth import verify_api_key
from app.camera import Camera
from app.worker_manager import manager
from app.config import ARM_SERVICE_URL

_start_time = time.time()

# Display timezone for read-only endpoints. DB always stores UTC; this is only
# applied when computing "today" boundaries or interpreting date_from/date_to
# filter inputs. Default GMT+7 (Indochina) preserves historical behaviour.
# Endpoints that touch user-facing dates accept ?tz=7|8 query param to support
# the dashboard's TZ toggle (browser-local switch only, never writes to DB).
DISPLAY_TZ = timezone(timedelta(hours=7))


def _resolve_display_tz(tz: int) -> timezone:
    """Whitelist tz to {7, 8}; anything else falls back to GMT+7. This is a
    purely read-side concern — no business logic depends on the result."""
    return timezone(timedelta(hours=tz if tz in (7, 8) else 7))

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
async def get_today_stats(tz: int = 7):
    """Today's transaction statistics. `tz` (7 or 8) selects the calendar day
    boundary used to count rows; defaults to GMT+7 for backward compat."""
    display_tz = _resolve_display_tz(tz)
    today_local = datetime.now(display_tz).date()
    start_local = datetime.combine(today_local, datetime.min.time(), tzinfo=display_tz)
    end_local = datetime.combine(today_local, datetime.max.time(), tzinfo=display_tz)
    start_utc = start_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    end_utc = end_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    rows = await database.fetchall(
        "SELECT status, COUNT(*) as cnt FROM transactions "
        "WHERE created_at >= %s AND created_at <= %s "
        "GROUP BY status",
        (start_utc, end_utc),
    )
    stats = {r["status"]: r["cnt"] for r in rows}

    # Per-arm breakdown for today: {arm_id: {success, total}} where total
    # counts success + failed + stall. Used by the dashboard arm cards to
    # show "Today: success/total". Replaces the old worker in-memory counter
    # which was independent of date / timezone.
    per_arm_rows = await database.fetchall(
        "SELECT s.arm_id, t.status, COUNT(*) AS cnt FROM transactions t "
        "JOIN stations s ON t.station_id = s.id "
        "WHERE t.created_at >= %s AND t.created_at <= %s "
        "AND t.status IN ('success', 'failed', 'stall') "
        "GROUP BY s.arm_id, t.status",
        (start_utc, end_utc),
    )
    per_arm = {}
    for row in per_arm_rows:
        bucket = per_arm.setdefault(row["arm_id"], {"success": 0, "total": 0})
        if row["status"] == "success":
            bucket["success"] = row["cnt"]
        bucket["total"] += row["cnt"]

    return {
        "success": stats.get("success", 0),
        "failed": stats.get("failed", 0),
        "stall": stats.get("stall", 0),
        "queued": stats.get("queued", 0),
        "running": stats.get("running", 0),
        "total": sum(stats.values()),
        "per_arm": per_arm,
    }


@router.get("/reports/summary")
async def reports_summary(date_from: str, date_to: str,
                          tz: int = 7, arm_id: int = None):
    """Aggregate report for a date range, in the requested display timezone.

    Returns 5 sections:
        summary             — overall {success, failed, stall, total, success_rate}
        per_arm             — list of {arm_id, arm_name, success, failed, stall, total, success_rate, avg_duration_s}
        per_bank            — list of {bank_code, success, failed, stall, total, success_rate}
        top_failing_steps   — list of {step_name, action_type, fail_count, sample_message}
        stall_reasons       — list of {reason, count} (top error_message values)
        slowest_steps       — list of {step_name, action_type, avg_ms, max_ms, count}

    All read-only; no business logic affected.
    """
    display_tz = _resolve_display_tz(tz)
    try:
        start_utc = (
            datetime.strptime(date_from, "%Y-%m-%d")
            .replace(hour=0, minute=0, second=0, tzinfo=display_tz)
            .astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        end_utc = (
            datetime.strptime(date_to, "%Y-%m-%d")
            .replace(hour=23, minute=59, second=59, tzinfo=display_tz)
            .astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return {"error": "date_from / date_to must be YYYY-MM-DD"}

    # Optional arm filter applied to all sections that have a station_id link.
    arm_clause = ""
    arm_params = ()
    if arm_id:
        arm_clause = " AND s.arm_id = %s"
        arm_params = (int(arm_id),)

    # --- 1. Overall summary -------------------------------------------------
    overall_rows = await database.fetchall(
        "SELECT t.status, COUNT(*) as cnt FROM transactions t "
        "JOIN stations s ON t.station_id = s.id "
        "WHERE t.created_at >= %s AND t.created_at <= %s" + arm_clause + " "
        "GROUP BY t.status",
        (start_utc, end_utc) + arm_params,
    )
    by_status = {r["status"]: r["cnt"] for r in overall_rows}
    overall_success = by_status.get("success", 0)
    overall_failed = by_status.get("failed", 0)
    overall_stall = by_status.get("stall", 0)
    overall_finished = overall_success + overall_failed + overall_stall
    summary = {
        "success": overall_success,
        "failed": overall_failed,
        "stall": overall_stall,
        "queued": by_status.get("queued", 0),
        "running": by_status.get("running", 0),
        "total": sum(by_status.values()),
        "finished": overall_finished,
        "success_rate": (round(overall_success / overall_finished * 100, 1)
                         if overall_finished > 0 else 0.0),
    }

    # --- 2. Per-arm ---------------------------------------------------------
    arm_status_rows = await database.fetchall(
        "SELECT a.id AS arm_id, a.name AS arm_name, t.status, COUNT(*) AS cnt "
        "FROM transactions t "
        "JOIN stations s ON t.station_id = s.id "
        "JOIN arms a ON s.arm_id = a.id "
        "WHERE t.created_at >= %s AND t.created_at <= %s" + arm_clause + " "
        "AND t.status IN ('success', 'failed', 'stall') "
        "GROUP BY a.id, a.name, t.status",
        (start_utc, end_utc) + arm_params,
    )
    arm_dur_rows = await database.fetchall(
        "SELECT a.id AS arm_id, "
        "AVG(TIMESTAMPDIFF(SECOND, t.started_at, t.finished_at)) AS avg_dur_s "
        "FROM transactions t "
        "JOIN stations s ON t.station_id = s.id "
        "JOIN arms a ON s.arm_id = a.id "
        "WHERE t.created_at >= %s AND t.created_at <= %s" + arm_clause + " "
        "AND t.started_at IS NOT NULL AND t.finished_at IS NOT NULL "
        "AND t.status IN ('success', 'failed', 'stall') "
        "GROUP BY a.id",
        (start_utc, end_utc) + arm_params,
    )
    arm_dur = {r["arm_id"]: float(r["avg_dur_s"] or 0) for r in arm_dur_rows}
    per_arm_map = {}
    for r in arm_status_rows:
        bucket = per_arm_map.setdefault(r["arm_id"], {
            "arm_id": r["arm_id"], "arm_name": r["arm_name"],
            "success": 0, "failed": 0, "stall": 0, "total": 0,
        })
        bucket[r["status"]] = r["cnt"]
        bucket["total"] += r["cnt"]
    per_arm = []
    for b in per_arm_map.values():
        b["success_rate"] = (round(b["success"] / b["total"] * 100, 1)
                             if b["total"] > 0 else 0.0)
        b["avg_duration_s"] = round(arm_dur.get(b["arm_id"], 0), 1)
        per_arm.append(b)
    per_arm.sort(key=lambda x: -x["total"])

    # --- 3. Per-bank --------------------------------------------------------
    bank_status_rows = await database.fetchall(
        "SELECT t.pay_from_bank_code AS bank_code, t.status, COUNT(*) AS cnt "
        "FROM transactions t "
        "JOIN stations s ON t.station_id = s.id "
        "WHERE t.created_at >= %s AND t.created_at <= %s" + arm_clause + " "
        "AND t.status IN ('success', 'failed', 'stall') "
        "GROUP BY t.pay_from_bank_code, t.status",
        (start_utc, end_utc) + arm_params,
    )
    per_bank_map = {}
    for r in bank_status_rows:
        bucket = per_bank_map.setdefault(r["bank_code"], {
            "bank_code": r["bank_code"],
            "success": 0, "failed": 0, "stall": 0, "total": 0,
        })
        bucket[r["status"]] = r["cnt"]
        bucket["total"] += r["cnt"]
    per_bank = []
    for b in per_bank_map.values():
        b["success_rate"] = (round(b["success"] / b["total"] * 100, 1)
                             if b["total"] > 0 else 0.0)
        per_bank.append(b)
    per_bank.sort(key=lambda x: -x["total"])

    # --- 4. Top failing steps (from transaction_logs) -----------------------
    # Filter logs by joining back to transactions for arm filter + date range.
    failing_rows = await database.fetchall(
        "SELECT l.step_name, l.action_type, COUNT(*) AS fail_count, "
        "MAX(LEFT(l.message, 200)) AS sample_message "
        "FROM transaction_logs l "
        "JOIN transactions t ON l.transaction_id = t.id "
        "JOIN stations s ON t.station_id = s.id "
        "WHERE l.result = 'fail' "
        "AND t.created_at >= %s AND t.created_at <= %s" + arm_clause + " "
        "GROUP BY l.step_name, l.action_type "
        "ORDER BY fail_count DESC LIMIT 10",
        (start_utc, end_utc) + arm_params,
    )
    top_failing_steps = [dict(r) for r in failing_rows]

    # --- 5. Stall reasons (truncated error_message buckets) -----------------
    stall_rows = await database.fetchall(
        "SELECT LEFT(t.error_message, 80) AS reason, COUNT(*) AS cnt "
        "FROM transactions t "
        "JOIN stations s ON t.station_id = s.id "
        "WHERE t.status = 'stall' AND t.error_message IS NOT NULL "
        "AND t.created_at >= %s AND t.created_at <= %s" + arm_clause + " "
        "GROUP BY reason ORDER BY cnt DESC LIMIT 10",
        (start_utc, end_utc) + arm_params,
    )
    stall_reasons = [{"reason": r["reason"], "count": r["cnt"]} for r in stall_rows]

    # --- 6. Slowest steps (avg duration_ms across all logs) -----------------
    slow_rows = await database.fetchall(
        "SELECT l.step_name, l.action_type, "
        "ROUND(AVG(l.duration_ms)) AS avg_ms, MAX(l.duration_ms) AS max_ms, "
        "COUNT(*) AS cnt "
        "FROM transaction_logs l "
        "JOIN transactions t ON l.transaction_id = t.id "
        "JOIN stations s ON t.station_id = s.id "
        "WHERE l.duration_ms IS NOT NULL AND l.duration_ms > 0 "
        "AND t.created_at >= %s AND t.created_at <= %s" + arm_clause + " "
        "GROUP BY l.step_name, l.action_type "
        "HAVING cnt >= 5 "
        "ORDER BY avg_ms DESC LIMIT 10",
        (start_utc, end_utc) + arm_params,
    )
    slowest_steps = [dict(r) for r in slow_rows]

    return {
        "summary": summary,
        "per_arm": per_arm,
        "per_bank": per_bank,
        "top_failing_steps": top_failing_steps,
        "stall_reasons": stall_reasons,
        "slowest_steps": slowest_steps,
        "filter": {
            "date_from": date_from,
            "date_to": date_to,
            "tz": tz,
            "arm_id": arm_id,
        },
    }


@router.get("/export/daily-summary", dependencies=[Depends(verify_api_key)])
async def export_daily_summary(date: str = None, tz: int = 7):
    """Authenticated daily summary for external report aggregation.

    If date is omitted, summarize yesterday in the requested display timezone.
    Only final statuses requested by operations are included: success/failed/stall.
    """
    if tz not in (7, 8):
        return {"error": "tz must be 7 or 8"}

    display_tz = _resolve_display_tz(tz)
    if date is None:
        report_date = (datetime.now(display_tz) - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return {"error": "date must be YYYY-MM-DD"}
        report_date = date

    start_utc = (
        datetime.strptime(report_date, "%Y-%m-%d")
        .replace(hour=0, minute=0, second=0, tzinfo=display_tz)
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%d %H:%M:%S")
    )
    end_utc = (
        datetime.strptime(report_date, "%Y-%m-%d")
        .replace(hour=23, minute=59, second=59, tzinfo=display_tz)
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%d %H:%M:%S")
    )

    rows = await database.fetchall(
        "SELECT a.id AS arm_id, a.name AS arm_name, "
        "t.pay_from_bank_code AS bank_code, t.status, COUNT(*) AS cnt "
        "FROM transactions t "
        "JOIN stations s ON t.station_id = s.id "
        "JOIN arms a ON s.arm_id = a.id "
        "WHERE t.created_at >= %s AND t.created_at <= %s "
        "AND t.status IN ('success', 'failed', 'stall') "
        "GROUP BY a.id, a.name, t.pay_from_bank_code, t.status "
        "ORDER BY a.name, t.pay_from_bank_code, t.status",
        (start_utc, end_utc),
    )

    total = {"total": 0, "success": 0, "failed": 0, "stall": 0}
    arms = {}
    for r in rows:
        arm = arms.setdefault(r["arm_id"], {
            "arm_id": r["arm_id"],
            "arm_name": r["arm_name"],
            "total": 0,
            "success": 0,
            "failed": 0,
            "stall": 0,
            "_banks": {},
        })
        bank = arm["_banks"].setdefault(r["bank_code"], {
            "bank_code": r["bank_code"],
            "total": 0,
            "success": 0,
            "failed": 0,
            "stall": 0,
        })

        status = r["status"]
        count = int(r["cnt"])
        arm[status] += count
        arm["total"] += count
        bank[status] += count
        bank["total"] += count
        total[status] += count
        total["total"] += count

    arm_list = []
    for arm in arms.values():
        banks = sorted(arm.pop("_banks").values(), key=lambda b: (-b["total"], b["bank_code"]))
        arm["banks"] = banks
        arm_list.append(arm)
    arm_list.sort(key=lambda a: (-a["total"], a["arm_name"]))

    return {
        "date": report_date,
        "tz": tz,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "total": total,
        "arms": arm_list,
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
                            limit: int = 50, offset: int = 0,
                            tz: int = 7):
    """List transactions with optional filters: status, bank, to_bank, arm_id,
    date range. `tz` (7 or 8) controls how date_from/date_to are interpreted
    as calendar-day boundaries; defaults to GMT+7."""
    display_tz = _resolve_display_tz(tz)
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
        # date_from is the display_tz calendar date; convert 00:00 boundary to UTC.
        dt_utc = (
            datetime.strptime(date_from, "%Y-%m-%d")
            .replace(hour=0, minute=0, second=0, tzinfo=display_tz)
            .astimezone(timezone.utc)
            .strftime("%Y-%m-%d %H:%M:%S")
        )
        where.append("t.created_at >= %s")
        params.append(dt_utc)
    if date_to:
        # date_to inclusive end-of-day in display_tz, converted to UTC.
        dt_utc = (
            datetime.strptime(date_to, "%Y-%m-%d")
            .replace(hour=23, minute=59, second=59, tzinfo=display_tz)
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


# DB status string ↔ PAS callback status code (per API_SPEC.md). Used by the
# manual callback-resend endpoint below.
_DB_TO_PAS_STATUS = {"success": 1, "failed": 2, "review": 3, "stall": 4}
_PAS_TO_DB_STATUS = {v: k for k, v in _DB_TO_PAS_STATUS.items()}


@router.post("/transactions/{transaction_id}/resend-callback")
async def resend_callback(transaction_id: int, data: dict):
    """Manually resend PAS callback for a finished transaction.

    Used when the auto retry chain (3x with 5s/15s/30s backoff in
    pas_client.callback_result) failed, or when an operator needs to correct
    the status after manually inspecting the receipt photo (e.g. flip a
    misclassified 'success' to 'stall').

    Body:
        status (int): PAS status code 1=success, 2=failed, 3=review, 4=stall.
            Whitelisted; any other value is rejected.
        include_receipt (bool, default true): attach receipt_base64 to the
            callback. Disabled automatically when the transaction has no receipt.
        update_db_status (bool, default true): also UPDATE transactions.status
            to match the chosen status before sending.

    Behaviour mirrors arm_worker's stall-callback ordering (DB update first,
    then PAS call, then callback_sent_at on success). On PAS failure the DB
    status change is preserved (the operator's claim about the truth doesn't
    revert just because PAS happens to be down) and callback_sent_at stays
    NULL so a retry remains possible.
    """
    from app import pas_client

    body_status = data.get("status")
    if body_status not in _PAS_TO_DB_STATUS:
        return {"ok": False, "error": "status must be 1, 2, 3 or 4"}

    include_receipt = bool(data.get("include_receipt", True))
    update_db_status = bool(data.get("update_db_status", True))

    tx = await database.fetchone(
        "SELECT id, process_id, status, finished_at, receipt_base64 "
        "FROM transactions WHERE id = %s", (transaction_id,))
    if not tx:
        return {"ok": False, "error": "Transaction not found"}
    if tx["status"] in ("queued", "running"):
        return {"ok": False, "error": "Transaction not finished yet"}
    if tx["finished_at"] is None:
        return {"ok": False, "error": "Transaction has no finished_at timestamp"}

    new_db_status = _PAS_TO_DB_STATUS[body_status]
    db_changed = False
    if update_db_status and tx["status"] != new_db_status:
        await database.execute(
            "UPDATE transactions SET status = %s WHERE id = %s",
            (new_db_status, transaction_id))
        db_changed = True

    transaction_datetime = tx["finished_at"].strftime("%Y-%m-%d %H:%M:%S")
    receipt = tx["receipt_base64"] if (include_receipt and tx["receipt_base64"]) else None

    cb_result = await pas_client.callback_result(
        tx["process_id"], body_status, transaction_datetime, receipt)

    if cb_result is None:
        logger.error("Resend callback FAILED for tx %d (process_id=%d, status=%d). "
                     "DB status change preserved=%s, callback_sent_at NOT updated.",
                     transaction_id, tx["process_id"], body_status, db_changed)
        return {
            "ok": False,
            "error": "PAS callback failed after retries",
            "db_status_changed": db_changed,
        }

    await database.execute(
        "UPDATE transactions SET callback_sent_at = NOW() WHERE id = %s",
        (transaction_id,))
    logger.info("Resend callback OK for tx %d (process_id=%d, status=%d, "
                "db_changed=%s, receipt=%s)",
                transaction_id, tx["process_id"], body_status,
                db_changed, "yes" if receipt else "no")
    return {
        "ok": True,
        "pas_response": cb_result,
        "db_status_changed": db_changed,
        "new_db_status": new_db_status if db_changed else tx["status"],
    }


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
