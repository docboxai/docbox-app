"""Engine-level storage: how much disk each engine's packages and models use, and
uninstalling an engine entirely (packages + every model it downloaded)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from docbox.backend.api.errors import http_errors
from docbox.backend.core.opener import open_path
from docbox.backend.core.paths import get_models_dir
from docbox.backend.schemas import EngineRemoveResult, StorageInfo
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


@router.delete("/{extra}", response_model=EngineRemoveResult)
def uninstall_engine(extra: str) -> EngineRemoveResult:
    with http_errors():
        return service.remove_engine(extra)
