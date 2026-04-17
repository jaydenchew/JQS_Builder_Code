"""Multi-arm Worker Manager — manages all ArmWorker instances.

Reads active arms from DB, creates a worker per arm, runs them as asyncio tasks.
Supports dynamic add/remove of workers without restarting the server.

Key design:
- asyncio.Lock guards all worker dict mutations to prevent race conditions
- _remove_worker() is the single atomic operation for stopping a worker:
    cancel task → await → _cleanup_arm() → stop executor
- set_offline() fully removes the worker from memory (stop() releases camera)
    so that resume() creates a fresh instance with a new camera
"""
import asyncio
import logging
from app import database
from app.arm_worker import ArmWorker

logger = logging.getLogger(__name__)


class WorkerManager:
    """Manages all ArmWorker instances"""

    def __init__(self):
        self.workers: dict[int, ArmWorker] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._events: dict[int, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    async def start_all(self):
        """Load active arms from DB and start a worker for each."""
        arms = await database.fetchall(
            "SELECT id, name, com_port, service_url, z_down, camera_id FROM arms WHERE active = 1"
        )
        if not arms:
            logger.warning("No active arms found in DB — no workers started")
            return

        for arm in arms:
            await self._create_worker(arm)

        logger.info("WorkerManager: %d workers started", len(self.workers))

    async def add_worker(self, arm_id: int) -> bool:
        """Dynamically add a worker for a new or reactivated arm."""
        async with self._lock:
            if arm_id in self.workers:
                logger.warning("Worker for arm %d already exists", arm_id)
                return True
            arm = await database.fetchone(
                "SELECT id, name, com_port, service_url, z_down, camera_id FROM arms WHERE id = %s", (arm_id,)
            )
            if not arm:
                logger.error("Arm %d not found in DB", arm_id)
                return False
            await self._create_worker(arm)
            logger.info("Dynamically added worker for arm %d (%s)", arm_id, arm["name"])
            return True

    async def _create_worker(self, arm: dict):
        """Instantiate ArmWorker and schedule its run() task. Caller must hold _lock.

        Creates a dedicated asyncio.Event per worker for event-driven task wakeup
        (replaces the old 2s polling loop). Event must be bound here so that both
        start_all() and add_worker() paths get the same treatment.
        """
        evt = asyncio.Event()
        self._events[arm["id"]] = evt
        worker = ArmWorker(
            arm_id=arm["id"],
            name=arm["name"],
            com_port=arm["com_port"],
            service_url=arm["service_url"],
            z_down=arm["z_down"],
            camera_id=arm["camera_id"],
            task_event=evt,
        )
        self.workers[arm["id"]] = worker
        task = asyncio.create_task(worker.run())
        self._tasks[arm["id"]] = task
        logger.info("Started worker for %s (arm_id=%d, %s, camera=%d)",
                    arm["name"], arm["id"], arm["com_port"], arm["camera_id"])

    async def _remove_worker(self, arm_id: int):
        """Atomic stop: cancel task → await → cleanup hardware → stop executor.

        Must be called while holding self._lock (or from stop_all which holds it).
        """
        task = self._tasks.pop(arm_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error("Worker task error during removal (arm %d): %s", arm_id, e)

        worker = self.workers.pop(arm_id, None)
        if worker:
            try:
                await worker._cleanup_arm()
            except Exception as e:
                logger.error("Cleanup error during removal (arm %d): %s", arm_id, e)
            worker.stop()

        self._events.pop(arm_id, None)

    async def stop_all(self):
        """Stop all workers gracefully: cancel → cleanup → stop executor."""
        async with self._lock:
            for arm_id in list(self.workers.keys()):
                await self._remove_worker(arm_id)
        logger.info("WorkerManager: all workers stopped and cleaned up")

    def get_all_status(self):
        return {arm_id: w.get_info() for arm_id, w in self.workers.items()}

    def get_worker(self, arm_id: int) -> ArmWorker | None:
        return self.workers.get(arm_id)

    def notify_worker(self, arm_id: int):
        """Wake up a worker's run() loop when a new task is inserted.

        Safe to call from any coroutine — asyncio.Event.set() is thread-safe
        when invoked from the event loop that owns the Event. Missing events
        are silently ignored (worker may have been removed).
        """
        evt = self._events.get(arm_id)
        if evt:
            evt.set()

    def pause(self, arm_id: int):
        worker = self.workers.get(arm_id)
        if worker:
            worker.pause()
            return True
        return False

    async def resume(self, arm_id: int) -> bool:
        """Resume or create a worker. Returns False if arm not found in DB."""
        worker = self.workers.get(arm_id)
        if worker:
            worker.resume()
            return True
        return await self.add_worker(arm_id)

    async def restart_worker(self, arm_id: int) -> bool:
        """Stop + recreate worker with fresh DB row.

        Used when arm config changes (camera_id, com_port, etc.) need to take
        effect without restarting the whole service. Returns False if arm is
        not found in DB or is inactive.
        """
        async with self._lock:
            await self._remove_worker(arm_id)
            arm = await database.fetchone(
                "SELECT id, name, com_port, service_url, z_down, camera_id, active FROM arms WHERE id = %s",
                (arm_id,)
            )
            if not arm:
                logger.error("restart_worker: arm %d not found in DB", arm_id)
                return False
            if not arm["active"]:
                logger.warning("restart_worker: arm %d is inactive — leaving stopped", arm_id)
                return False
            await self._create_worker(arm)
            return True

    async def set_offline(self, arm_id: int):
        """Fully stop and remove worker from memory + mark DB offline.

        Resume after set_offline will create a fresh ArmWorker instance,
        ensuring camera is freshly initialized on restart.
        """
        worker = self.workers.get(arm_id)
        arm_name = worker.name if worker else "arm_%d" % arm_id
        logger.warning(
            "[%s] Set to offline (temporary stop). Will auto-resume on service restart if arms.active = 1.",
            arm_name
        )
        async with self._lock:
            await self._remove_worker(arm_id)
        await database.execute("UPDATE arms SET status = 'offline' WHERE id = %s", (arm_id,))
        return True


# Singleton instance
manager = WorkerManager()
