"""Single-arm worker — refactored from JQS_Code worker.py to support multi-instance.

Each ArmWorker owns an ArmClient + Camera instance and processes tasks assigned to its arm.
Includes a per-worker log collector with ring buffer for real-time UI streaming.
"""
import time
import asyncio
import logging
import datetime
import collections
import threading
from concurrent.futures import ThreadPoolExecutor
from app.arm_client import ArmClient
from app.camera import Camera
from app import database, actions, pas_client

logger = logging.getLogger(__name__)

LOG_BUFFER_SIZE = 500


class WorkerLogHandler(logging.Handler):
    """Custom logging handler that captures log records into a ring buffer.

    Accepts logs that mention the arm name in the message OR originate from
    the worker's own executor thread (thread name starts with arm name).
    Uses a lock to make drain_new() thread-safe.
    """

    def __init__(self, buffer: collections.deque, arm_name: str):
        super().__init__()
        self._buffer = buffer
        self._arm_name = arm_name
        self._new_logs: list = []
        self._drain_lock = threading.Lock()

    def emit(self, record):
        msg = self.format(record)
        thread_name = getattr(record, "threadName", "")
        if self._arm_name not in msg and not thread_name.startswith(self._arm_name):
            return
        entry = {
            "ts": datetime.datetime.now().strftime("%H:%M:%S"),
            "level": record.levelname,
            "msg": msg,
        }
        self._buffer.append(entry)
        with self._drain_lock:
            self._new_logs.append(entry)

    def drain_new(self) -> list:
        """Return and clear new logs since last drain (thread-safe)."""
        with self._drain_lock:
            logs = self._new_logs
            self._new_logs = []
        return logs


class ArmWorker:
    """Independent worker for one mechanical arm"""

    def __init__(self, arm_id: int, name: str, com_port: str, service_url: str,
                 z_down: int, camera_id: int):
        self.arm_id = arm_id
        self.name = name
        self.arm_client = ArmClient(com_port=com_port, service_url=service_url, z_down=z_down)
        self.camera = Camera(camera_id=camera_id)
        self._paused = False
        self._running = False
        self._current_task = None
        self._current_step = None
        self._task_count = 0
        self._last_error = None

        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)

        self._log_buffer = collections.deque(maxlen=LOG_BUFFER_SIZE)
        self._log_handler = WorkerLogHandler(self._log_buffer, name)
        self._log_handler.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
        logging.getLogger("app").addHandler(self._log_handler)

    async def run(self):
        """Main loop: fetch and process tasks assigned to this arm."""
        self._running = True
        self.camera.camera_enable()
        await database.execute("UPDATE arms SET status = 'idle' WHERE id = %s", (self.arm_id,))
        logger.info("[%s] Worker started (arm_id=%d)", self.name, self.arm_id)

        while self._running:
            if self._paused:
                await asyncio.sleep(2)
                continue

            task = await self._fetch_next_task()
            if not task:
                await asyncio.sleep(2)
                continue

            await self._process_task(task)

        logger.info("[%s] Worker stopped", self.name)

    async def _fetch_next_task(self):
        """Get next queued task for stations belonging to this arm."""
        return await database.fetchone(
            """SELECT t.*, ba.password, ba.pin, ba.bank_code as app_bank_code
            FROM transactions t
            JOIN bank_apps ba ON t.bank_app_id = ba.id
            JOIN stations s ON t.station_id = s.id
            WHERE t.status = 'queued' AND s.arm_id = %s
            ORDER BY t.created_at ASC
            LIMIT 1""",
            (self.arm_id,)
        )

    async def _process_task(self, task):
        process_id = task["process_id"]
        bank_code = task["pay_from_bank_code"]
        station_id = task["station_id"]
        password = task["password"]
        transaction_id = task["id"]

        task["_arm_name"] = self.name
        self._current_task = process_id
        self._current_step = "starting"
        logger.info("[%s] === START task: process_id=%d bank=%s station=%d ===",
                     self.name, process_id, bank_code, station_id)

        await database.execute(
            "UPDATE transactions SET status = 'running', started_at = NOW() WHERE id = %s",
            (transaction_id,)
        )
        await database.execute("UPDATE arms SET status = 'busy' WHERE id = %s", (self.arm_id,))

        success = False
        error_msg = None

        try:
            success = await self._execute_task(task, bank_code, station_id, password, transaction_id)
        except RuntimeError as e:
            error_str = str(e)
            if "port open failed" in error_str.lower() or "not responding" in error_str.lower():
                logger.error("[%s] Hardware error, pausing 30s: %s", self.name, e)
                await asyncio.sleep(30)
            error_msg = error_str
            logger.error("[%s] Task error: %s", self.name, e)
        except Exception as e:
            error_msg = str(e)
            logger.exception("[%s] Task error: %s", self.name, e)

        ocr_result = task.get("_ocr_result")
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        receipt_b64 = None

        row = await database.fetchone(
            "SELECT receipt_base64 FROM transactions WHERE id = %s", (transaction_id,))
        if row and row["receipt_base64"]:
            receipt_b64 = row["receipt_base64"]

        if not receipt_b64 and ocr_result and ocr_result.get("screenshot_b64"):
            receipt_b64 = ocr_result["screenshot_b64"]

        if success and ocr_result and ocr_result.get("is_receipt_check"):
            rr = ocr_result.get("receipt_result")
            status_map = {"success": 1, "failed": 2, "fail": 2, "review": 3}
            pas_status = status_map.get(rr, 1)
            db_status = "success" if pas_status == 1 else "failed"

            await database.execute(
                "UPDATE transactions SET status = %s, finished_at = NOW() WHERE id = %s",
                (db_status, transaction_id))
            cb_result = await pas_client.callback_result(process_id, pas_status, now, receipt_b64)
            if cb_result is not None:
                await database.execute(
                    "UPDATE transactions SET callback_sent_at = NOW() WHERE id = %s", (transaction_id,))
            else:
                logger.error("[%s] PAS callback failed for process_id=%d, callback_sent_at NOT updated", self.name, process_id)
            logger.info("[%s] === DONE process_id=%d pas_status=%d receipt=%s ===",
                        self.name, process_id, pas_status, rr)

        elif success:
            await database.execute(
                "UPDATE transactions SET status = 'success', finished_at = NOW() WHERE id = %s",
                (transaction_id,))
            cb_result = await pas_client.callback_result(process_id, 1, now, receipt_b64)
            if cb_result is not None:
                await database.execute(
                    "UPDATE transactions SET callback_sent_at = NOW() WHERE id = %s", (transaction_id,))
            else:
                logger.error("[%s] PAS callback failed for process_id=%d, callback_sent_at NOT updated", self.name, process_id)
            logger.info("[%s] === SUCCESS process_id=%d ===", self.name, process_id)

        else:
            if not error_msg:
                if ocr_result and not ocr_result.get("success"):
                    error_msg = "OCR verification failed"
                else:
                    error_msg = "Step execution failed"
            self._last_error = error_msg

            stall_screenshot = await self._capture_stall_photo(station_id)
            if stall_screenshot:
                receipt_b64 = stall_screenshot

            await database.execute(
                "UPDATE transactions SET status = 'stall', error_message = %s, receipt_base64 = %s, finished_at = NOW() WHERE id = %s",
                (error_msg, receipt_b64, transaction_id))
            cb_result = await pas_client.callback_result(process_id, 4, now, receipt_b64)
            if cb_result is not None:
                await database.execute(
                    "UPDATE transactions SET callback_sent_at = NOW() WHERE id = %s", (transaction_id,))
            else:
                logger.error("[%s] PAS callback failed for process_id=%d, callback_sent_at NOT updated", self.name, process_id)
            logger.warning("[%s] === STALL process_id=%d error=%s ===", self.name, process_id, error_msg)

        await self._cleanup_arm()

        if not success:
            await database.execute("UPDATE arms SET status = 'offline' WHERE id = %s", (self.arm_id,))
            await self._fail_queued_tasks("ARM %s stalled — previous task failed, queued tasks auto-rejected" % self.name)
            self._paused = True
            logger.warning("[%s] ARM PAUSED — needs manual inspection", self.name)
        else:
            await database.execute("UPDATE arms SET status = 'idle' WHERE id = %s", (self.arm_id,))

        self._current_task = None
        self._current_step = None
        self._task_count += 1

    async def _execute_task(self, task, bank_code, station_id, password, transaction_id):
        """Execute the data-driven flow. Returns True on success."""
        transfer_type = "SAME" if task["pay_from_bank_code"] == task["pay_to_bank_code"] else "INTER"

        flow = await database.fetchone(
            "SELECT id, amount_format FROM flow_templates WHERE bank_code = %s AND arm_id = %s AND transfer_type = %s AND status = 'active' ORDER BY version DESC LIMIT 1",
            (bank_code, self.arm_id, transfer_type),
        )
        if not flow:
            flow = await database.fetchone(
                "SELECT id, amount_format FROM flow_templates WHERE bank_code = %s AND arm_id = %s AND transfer_type IS NULL AND status = 'active' ORDER BY version DESC LIMIT 1",
                (bank_code, self.arm_id),
            )
        if not flow:
            flow = await database.fetchone(
                "SELECT id, amount_format FROM flow_templates WHERE bank_code = %s AND arm_id IS NULL AND transfer_type = %s AND status = 'active' ORDER BY version DESC LIMIT 1",
                (bank_code, transfer_type),
            )
        if not flow:
            flow = await database.fetchone(
                "SELECT id, amount_format FROM flow_templates WHERE bank_code = %s AND arm_id IS NULL AND transfer_type IS NULL AND status = 'active' ORDER BY version DESC LIMIT 1",
                (bank_code,),
            )
        if not flow:
            raise RuntimeError("No active flow template for bank: %s (transfer_type=%s)" % (bank_code, transfer_type))

        task["_amount_format"] = flow.get("amount_format")

        steps = await database.fetchall(
            "SELECT * FROM flow_steps WHERE flow_template_id = %s ORDER BY step_number ASC",
            (flow["id"],)
        )
        if not steps:
            raise RuntimeError("No flow steps for template: %d" % flow["id"])

        logger.info("[%s] Loaded %d steps for %s (template=%d)", self.name, len(steps), bank_code, flow["id"])

        await self._hw(self.arm_client.open_port)
        await self._hw(self.arm_client.motor_lock)
        await self._hw(self.arm_client.reset_to_origin)

        for step in steps:
            step_name = step["step_name"]
            step_number = step["step_number"]
            action_type = step["action_type"]

            if step_name == "done":
                logger.info("[%s] Step %d: done", self.name, step_number)
                break

            self._current_step = "%d/%d %s" % (step_number, len(steps), step_name)
            logger.info("[%s] Step %s (%s)", self.name, self._current_step, action_type)

            ok = await actions.execute_step(
                step, bank_code, station_id, task, password, transaction_id,
                arm=self.arm_client, cam=self.camera, executor=self._executor
            )
            if not ok:
                logger.error("[%s] Step %d failed, aborting", self.name, step_number)
                return False

        return True

    async def _hw(self, func, *args):
        """Run blocking hardware operation in worker's dedicated thread."""
        return await asyncio.get_event_loop().run_in_executor(self._executor, func, *args)

    async def _fail_queued_tasks(self, message: str):
        """When arm stalls, reject all queued tasks for this arm and callback PAS with status=4."""
        from datetime import datetime, timezone
        rows = await database.fetchall(
            "SELECT id, process_id FROM transactions WHERE station_id IN "
            "(SELECT id FROM stations WHERE arm_id = %s) AND status = 'queued'",
            (self.arm_id,))
        if not rows:
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for t in rows:
            await database.execute(
                "UPDATE transactions SET status = 'failed', error_message = %s, finished_at = NOW() WHERE id = %s",
                (message, t["id"]))
            await pas_client.callback_result(t["process_id"], 4, now)
            await database.execute(
                "UPDATE transactions SET callback_sent_at = NOW() WHERE id = %s", (t["id"],))
            logger.warning("[%s] Queued task rejected: process_id=%d — %s", self.name, t["process_id"], message)
        logger.info("[%s] Rejected %d queued tasks", self.name, len(rows))

    async def _capture_stall_photo(self, station_id: int) -> str | None:
        """Move arm to station's stall photo position and capture full-screen screenshot.
        Returns base64 JPEG or None if position not configured / hardware error.
        """
        try:
            station = await database.fetchone(
                "SELECT stall_photo_x, stall_photo_y FROM stations WHERE id = %s", (station_id,))
            if not station or station["stall_photo_x"] is None or station["stall_photo_y"] is None:
                logger.info("[%s] No stall photo position configured for station %d, using current position",
                            self.name, station_id)
                return await self._hw(self.camera.capture_base64)

            await self._hw(self.arm_client.move, station["stall_photo_x"], station["stall_photo_y"])
            await asyncio.sleep(1)
            b64 = await self._hw(self.camera.capture_base64)
            logger.info("[%s] Stall photo captured at (%.1f, %.1f)",
                        self.name, station["stall_photo_x"], station["stall_photo_y"])
            return b64
        except Exception as e:
            logger.error("[%s] Stall photo capture failed: %s", self.name, e)
            return None

    async def _cleanup_arm(self):
        if self.arm_client.is_connected():
            try:
                await self._hw(self.arm_client.reset_to_origin)
                await self._hw(self.arm_client.close_port)
            except Exception as e:
                logger.error("[%s] Arm cleanup failed: %s", self.name, e)
        self.camera.camera_close()

    def pause(self):
        self._paused = True
        logger.info("[%s] Paused", self.name)

    def resume(self):
        self._paused = False
        self._last_error = None
        logger.info("[%s] Resumed", self.name)

    def stop(self):
        self._running = False
        self.camera.camera_disable()
        logging.getLogger("app").removeHandler(self._log_handler)
        self._executor.shutdown(wait=False)

    def get_status(self):
        if not self._running:
            return "offline"
        if self._paused:
            return "paused"
        if self._current_task:
            return "busy"
        return "idle"

    def get_info(self):
        return {
            "arm_id": self.arm_id,
            "name": self.name,
            "status": self.get_status(),
            "current_task": self._current_task,
            "current_step": self._current_step,
            "task_count": self._task_count,
            "last_error": self._last_error,
        }

    def get_logs(self, limit: int = 200) -> list:
        """Return recent log entries from the ring buffer."""
        logs = list(self._log_buffer)
        return logs[-limit:]

    def drain_new_logs(self) -> list:
        """Return new logs since last drain (for WebSocket push)."""
        return self._log_handler.drain_new()
