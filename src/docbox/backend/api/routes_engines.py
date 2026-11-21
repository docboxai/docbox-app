"""Engine-level storage: how much disk each engine's packages and models use, and
uninstalling an engine entirely (packages + every model it downloaded)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Response

from docbox.backend.api.errors import http_errors
from docbox.backend.core.opener import open_path
from docbox.backend.core.paths import get_models_dir
from docbox.backend.schemas import (
    DownloadStatus,
    EngineBuildRequest,
    EngineRemoveResult,
    GpuStatus,
    StorageInfo,
)
from docbox.service import engines as service

router = APIRouter(prefix="/api/engines", tags=["engines"])


@router.get("/storage", response_model=StorageInfo)
def storage() -> StorageInfo:
    return service.storage()


@router.post("/storage/open", status_code=204)
def open_storage() -> Response:
    """Show DocBox's models folder in the file manager."""
    open_path(get_models_dir())
    return Response(status_code=204)


@router.get("/gpu", response_model=GpuStatus)
def gpu_status() -> GpuStatus:
    """The graphics card, whether DocBox's engines can read on it, and each engine's build."""
    return service.gpu_status()


@router.post("/{extra}/build", response_model=DownloadStatus, status_code=202)
def switch_build(
    extra: str, body: EngineBuildRequest, background_tasks: BackgroundTasks
) -> DownloadStatus:
    """Install the engine's graphics-card or CPU build in place of the other; poll
    /build/status with the job id."""
    with http_errors():
        return service.start_switch_build(extra, body.build, background_tasks.add_task)


@router.get("/build/status", response_model=DownloadStatus)
def build_status(job_id: str) -> DownloadStatus:
    with http_errors():
        return service.build_status(job_id)


@router.delete("/{extra}", response_model=EngineRemoveResult)
def uninstall_engine(extra: str) -> EngineRemoveResult:
    with http_errors():
        return service.remove_engine(extra)
