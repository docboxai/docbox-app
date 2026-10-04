"""Engine-level storage: how much disk each engine's packages and models use, and
uninstalling an engine entirely (packages + every model it downloaded)."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from docbox.backend.core import runtime
from docbox.backend.core.jobs import job_store
from docbox.backend.core.opener import open_path
from docbox.backend.core.paths import get_data_dir, get_models_dir
from docbox.backend.core.registry import ModelSpec, registry
from docbox.backend.schemas import EngineRemoveResult, EngineStorage, StorageInfo

router = APIRouter(prefix="/api/engines", tags=["engines"])

# Where each extra's engines keep their downloaded weights, under the models dir.
_MODEL_DIRS: dict[str, tuple[str, ...]] = {
    "paddle": ("paddlex_cache",),
    "easyocr": ("easyocr",),
}


def _dir_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _model_dirs(extra: str) -> list[Path]:
    root = get_models_dir()
    return [root / d for d in _MODEL_DIRS[extra]]


@router.get("/storage", response_model=StorageInfo)
def storage() -> StorageInfo:
    installed = runtime.installed_extras()
    state = runtime.read_state()
    pending = bool(state.get("resync_pending"))
    engines = []
    for extra, (label, _marker) in runtime.EXTRAS.items():
        model_bytes = sum(_dir_bytes(d) for d in _model_dirs(extra))
        engines.append(
            EngineStorage(
                id=extra,
                name=label,
                installed=extra in installed,
                can_install=runtime.can_install(),
                package_bytes=runtime.extra_package_bytes(extra) if extra in installed else 0,
                model_bytes=model_bytes,
                models_downloaded=sum(
                    1 for s in registry.list()
                    if s.requires_extra == extra and model_bytes and _cheap_downloaded(s)
                ),
                removal_pending=pending and extra in installed
                and extra not in state.get("extras", []),
            )
        )
    return StorageInfo(data_dir=str(get_data_dir()), engines=engines)


@router.post("/storage/open", status_code=204)
def open_storage() -> Response:
    """Show DocBox's models folder in the file manager."""
    open_path(get_models_dir())
    return Response(status_code=204)


def _cheap_downloaded(spec: ModelSpec) -> bool:
    # Paddle's check is a directory lookup; EasyOCR's builds a Reader (imports torch), so
    # for it fall back to "has weight files" rather than loading PyTorch just to count.
    if spec.requires_extra == "easyocr":
        return any((get_models_dir() / "easyocr").glob("*.pth"))
    try:
        return spec.engine_factory().is_downloaded()
    except Exception:  # noqa: BLE001
        return False


@router.delete("/{extra}", response_model=EngineRemoveResult)
def uninstall_engine(extra: str) -> EngineRemoveResult:
    if extra not in runtime.EXTRAS:
        raise HTTPException(status_code=404, detail=f"Unknown engine: {extra}")
    for spec in registry.list():
        if spec.requires_extra == extra and job_store.active_for(spec.id) is not None:
            raise HTTPException(status_code=409, detail=f"{spec.name} is downloading; wait for it.")

    for d in _model_dirs(extra):
        shutil.rmtree(d, ignore_errors=True)

    label = runtime.EXTRAS[extra][0]
    if not runtime.extra_installed(extra):
        return EngineRemoveResult(removed=True, pending_restart=False,
                                  detail=f"{label}: models removed.")
    try:
        runtime.remove_extra(extra)
    except runtime.RemovalNeedsRestart as exc:
        return EngineRemoveResult(removed=False, pending_restart=True, detail=str(exc))
    except runtime.EngineInstallError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None
    return EngineRemoveResult(removed=True, pending_restart=False,
                              detail=f"{label} and its models were removed.")
