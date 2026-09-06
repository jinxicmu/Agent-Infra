import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Optional

from app import config


class JobStore:
    """One JSON file per task under jobs/. Atomic writes; reconstructable from disk."""

    def __init__(self, jobs_dir: Path = config.JOBS_DIR):
        self.jobs_dir = jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._cache: dict[str, dict] = {}
        self._load_all()

    def _path(self, task_id: str) -> Path:
        return self.jobs_dir / f"{task_id}.json"

    def _load_all(self):
        for f in self.jobs_dir.glob("*.json"):
            try:
                with open(f) as fh:
                    job = json.load(fh)
                self._cache[job["task_id"]] = job
            except (json.JSONDecodeError, KeyError, OSError):
                continue

    def create(self, job: dict):
        job["created_at"] = job.get("created_at", int(time.time()))
        job["updated_at"] = job["created_at"]
        with self._lock:
            self._cache[job["task_id"]] = job
            self._write(job)

    def update(self, task_id: str, **fields):
        with self._lock:
            job = self._cache[task_id]
            job.update(fields)
            job["updated_at"] = int(time.time())
            self._write(job)
            return job

    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            return self._cache.get(task_id)

    def all_jobs(self) -> list[dict]:
        with self._lock:
            return list(self._cache.values())

    def _write(self, job: dict):
        path = self._path(job["task_id"])
        tmp_path = path.with_suffix(".json.tmp")
        with open(tmp_path, "w") as f:
            json.dump(job, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)


job_store = JobStore()
