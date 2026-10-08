from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response

from docbox.backend.api.errors import http_errors
from docbox.backend.core.jobs import job_store
from docbox.backend.schemas import (
    DownloadStartResponse,
    DownloadStatus,
    ModelInfo,
)
from docbox.service import models as service

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=list[ModelInfo])
def list_models() -> list[ModelInfo]:
    return service.list_models()


@router.get("/{model_id}", response_model=ModelInfo)
def get_model(model_id: str) -> ModelInfo:
    with http_errors():
        return service.get_model(model_id)


@router.post("/{model_id}/download", response_model=DownloadStartResponse, status_code=202)
def start_download(model_id: str, background_tasks: BackgroundTasks) -> DownloadStartResponse:
    # A second click while it's already going rejoins the running job instead of
    # starting a duplicate download into the same files.
    with http_errors():
        job = service.start_install(model_id, background_tasks.add_task)
    return DownloadStartResponse(job_id=job.job_id)


@router.get("/{model_id}/download/status", response_model=DownloadStatus)
def download_status(model_id: str, job_id: str) -> DownloadStatus:
    job = job_store.get(job_id)
    if job is None or job.model_id != model_id:
        raise HTTPException(status_code=404, detail=f"Unknown download job: {job_id}")
    return service.job_status(job)


@router.post("/{model_id}/download/pause", response_model=DownloadStatus)
def pause_download(model_id: str, job_id: str) -> DownloadStatus:
    """Ask a running download to stop at its next progress report; starting the download
    again resumes it (Ollama keeps partial layers; the other engines redo the file that
    was in flight)."""
    job = job_store.get(job_id)
    if job is None or job.model_id != model_id:
        raise HTTPException(status_code=404, detail=f"Unknown download job: {job_id}")
    if job_store.request_pause(job_id):
        job_store.update(job_id, message="pausing after the current step")
    return service.job_status(job)


@router.delete("/{model_id}", status_code=204)
def delete_model(model_id: str) -> Response:
    with http_errors():
        service.remove_model(model_id)
    return Response(status_code=204)
