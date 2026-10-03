"""In-memory download-job tracking, backing the /download/status polling endpoint."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass

from docbox.backend.schemas import DownloadState


@dataclass
class DownloadJob:
    job_id: str
    model_id: str
    state: DownloadState = "pending"
    progress_pct: float | None = 0.0
    message: str | None = None


class DownloadJobStore:
    """Thread-safe because download work runs on FastAPI's threadpool, not the event loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, DownloadJob] = {}

    def create(self, model_id: str) -> DownloadJob:
        job = DownloadJob(job_id=str(uuid.uuid4()), model_id=model_id)
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> DownloadJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def active_for(self, model_id: str) -> DownloadJob | None:
        with self._lock:
            for job in self._jobs.values():
                if job.model_id == model_id and job.state not in ("done", "error"):
                    return job
        return None

    def update(
        self,
        job_id: str,
        *,
        state: DownloadState | None = None,
        progress_pct: float | None = None,
        message: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if state is not None:
                job.state = state
            if progress_pct is not None:
                job.progress_pct = progress_pct
            if message is not None:
                job.message = message


job_store = DownloadJobStore()
