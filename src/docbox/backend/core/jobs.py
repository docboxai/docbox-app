"""In-memory download-job tracking, backing the /download/status polling endpoint."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass

from docbox.backend.schemas import DownloadState

_FINISHED: tuple[DownloadState, ...] = ("done", "error")


class JobPaused(Exception):
    """Raised from a job's progress callback once the user has asked to pause it, so the
    download unwinds at its next progress report (engines report at different grains:
    every chunk for Tesseract and Ollama, every output line for package installs, only
    between model files for PaddleOCR)."""


@dataclass
class DownloadJob:
    job_id: str
    model_id: str
    state: DownloadState = "pending"
    progress_pct: float | None = 0.0
    message: str | None = None
    pause_requested: bool = False


class DownloadJobStore:
    """Thread-safe because download work runs on FastAPI's threadpool, not the event loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, DownloadJob] = {}

    def create(self, model_id: str, *, progress_pct: float = 0.0) -> DownloadJob:
        job = DownloadJob(job_id=str(uuid.uuid4()), model_id=model_id, progress_pct=progress_pct)
        with self._lock:
            # A new job resumes any paused one; the paused record has nothing left to say.
            self._jobs = {
                jid: j for jid, j in self._jobs.items()
                if not (j.model_id == model_id and j.state == "paused")
            }
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> DownloadJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def active_for(self, model_id: str) -> DownloadJob | None:
        """The model's running job (not paused or finished), if any."""
        with self._lock:
            for job in self._jobs.values():
                if job.model_id == model_id and job.state not in (*_FINISHED, "paused"):
                    return job
        return None

    def unfinished_for(self, model_id: str) -> DownloadJob | None:
        """The model's running or paused job, if any."""
        with self._lock:
            for job in self._jobs.values():
                if job.model_id == model_id and job.state not in _FINISHED:
                    return job
        return None

    def discard_paused(self, model_id: str) -> None:
        with self._lock:
            self._jobs = {
                jid: j for jid, j in self._jobs.items()
                if not (j.model_id == model_id and j.state == "paused")
            }

    def request_pause(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state in (*_FINISHED, "paused"):
                return False
            job.pause_requested = True
            return True

    def pause_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return job is not None and job.pause_requested

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
