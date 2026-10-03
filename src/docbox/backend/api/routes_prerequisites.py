from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from docbox.backend.core import prerequisites
from docbox.backend.core.jobs import job_store
from docbox.backend.schemas import DownloadStartResponse, DownloadStatus, PrerequisiteInfo

router = APIRouter(prefix="/api/prerequisites", tags=["prerequisites"])


def _check(prereq_id: str) -> None:
    if prereq_id not in prerequisites.PREREQUISITES:
        raise HTTPException(status_code=404, detail=f"Unknown prerequisite: {prereq_id}")


@router.get("", response_model=list[PrerequisiteInfo])
def list_prerequisites() -> list[PrerequisiteInfo]:
    return [PrerequisiteInfo(**p) for p in prerequisites.list_all()]


@router.get("/{prereq_id}", response_model=PrerequisiteInfo)
def get_prerequisite(prereq_id: str) -> PrerequisiteInfo:
    _check(prereq_id)
    return PrerequisiteInfo(**prerequisites.describe(prereq_id))


def _run_install(job_id: str, prereq_id: str) -> None:
    def cb(pct: float, message: str) -> None:
        job_store.update(job_id, state="installing", progress_pct=pct, message=message)

    try:
        prerequisites.install(prereq_id, cb)
        job_store.update(job_id, state="done", progress_pct=100.0, message="installed")
    except Exception as exc:  # noqa: BLE001
        job_store.update(job_id, state="error", message=str(exc))


@router.post("/{prereq_id}/install", response_model=DownloadStartResponse, status_code=202)
def start_install(prereq_id: str, background_tasks: BackgroundTasks) -> DownloadStartResponse:
    _check(prereq_id)
    if not prerequisites.can_auto_install():
        raise HTTPException(
            status_code=400,
            detail="One-click install is only available on Windows; run the shown command.",
        )
    key = f"prereq:{prereq_id}"
    active = job_store.active_for(key)
    if active is not None:
        return DownloadStartResponse(job_id=active.job_id)
    job = job_store.create(key)
    background_tasks.add_task(_run_install, job.job_id, prereq_id)
    return DownloadStartResponse(job_id=job.job_id)


@router.get("/{prereq_id}/install/status", response_model=DownloadStatus)
def install_status(prereq_id: str, job_id: str) -> DownloadStatus:
    job = job_store.get(job_id)
    if job is None or job.model_id != f"prereq:{prereq_id}":
        raise HTTPException(status_code=404, detail=f"Unknown install job: {job_id}")
    return DownloadStatus(
        job_id=job.job_id,
        model_id=job.model_id,
        state=job.state,
        progress_pct=job.progress_pct,
        message=job.message,
    )


@router.post("/ollama/start", response_model=PrerequisiteInfo)
def start_ollama() -> PrerequisiteInfo:
    try:
        prerequisites.start_ollama()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return PrerequisiteInfo(**prerequisites.describe("ollama"))
