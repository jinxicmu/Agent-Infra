from collections import deque
from threading import Lock

from app.job_store import job_store

PENDING_STATUSES = ("accepted", "queued")
ACTIVE_STATUSES = ("prefetched", "running", "uploading")
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


class Scheduler:
    """Non-preemptive priority queue: realtime before batch, oldest first within each.
    Backed by job_store for durability; queues are reconstructed from disk on init.
    """

    def __init__(self):
        self._lock = Lock()
        self._realtime: deque[str] = deque()
        self._batch: deque[str] = deque()
        self._reconstruct()

    def _reconstruct(self):
        jobs = sorted(job_store.all_jobs(), key=lambda j: j["created_at"])
        for job in jobs:
            if job["status"] in PENDING_STATUSES:
                (self._realtime if job["mode"] == "realtime" else self._batch).append(job["task_id"])

    def enqueue(self, task_id: str, mode: str):
        with self._lock:
            (self._realtime if mode == "realtime" else self._batch).append(task_id)

    def pending_count(self, mode: str) -> int:
        with self._lock:
            return len(self._realtime if mode == "realtime" else self._batch)

    def pop_next(self) -> str | None:
        """Realtime outranks batch; oldest-first within each. No preemption of running work."""
        with self._lock:
            if self._realtime:
                return self._realtime.popleft()
            if self._batch:
                return self._batch.popleft()
            return None


scheduler = Scheduler()
