"""Engine-level storage: how much disk each engine's packages and models use, and
uninstalling an engine entirely (packages + every model it downloaded). And each engine's
build: the CPU one every engine starts with, or the graphics-card one the user can switch
to (core/runtime.py's GPU_BUILDS, core/gpu.py)."""

from __future__ import annotations

import shutil
import threading
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

from filelock import Timeout

import docbox.backend.models_catalog  # noqa: F401 — importing it fills the registry
from docbox.backend.core import device, engine_cache, gpu, runtime
from docbox.backend.core.jobs import job_store
from docbox.backend.core.locks import model_lock
from docbox.backend.core.paths import get_data_dir, get_models_dir
from docbox.backend.core.registry import ModelSpec, registry
from docbox.backend.schemas import (
    DownloadStatus,
    EngineGpuBuild,
    EngineRemoveResult,
    EngineStorage,
    GpuStatus,
    StorageInfo,
)
from docbox.service.errors import Conflict, Failed, Invalid, NotFound

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


def _cheap_downloaded(spec: ModelSpec) -> bool:
    # Paddle's check is a directory lookup; EasyOCR's builds a Reader (imports torch), so
    # for it fall back to "has weight files" rather than loading PyTorch just to count.
    if spec.requires_extra == "easyocr":
        return any((get_models_dir() / "easyocr").glob("*.pth"))
    try:
        return spec.engine_factory().is_downloaded()
    except Exception:  # noqa: BLE001
        return False


def storage() -> StorageInfo:
    installed = runtime.installed_extras()
    pending = bool(runtime.read_state().get("resync_pending"))
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
                and extra not in runtime.state_engines(),
            )
        )
    return StorageInfo(
        data_dir=str(get_data_dir()),
        models_bytes=_dir_bytes(get_models_dir()),
        engines=engines,
    )


def _engine_specs(extra: str) -> list[ModelSpec]:
    specs = [s for s in registry.list() if s.requires_extra == extra]
    for spec in specs:
        if job_store.active_for(spec.id) is not None:
            raise Conflict(f"{spec.name} is downloading; wait for it.")
    return specs


def _hold_model_locks(held: ExitStack, specs: list[ModelSpec]) -> None:
    """The data dir is shared with the CLI, the MCP server and the app: hold every one of
    an engine's install locks while its packages or files change, so another process
    can't be installing one of its models at the same time."""
    for spec in specs:
        lock = model_lock(spec.id)
        try:
            lock.acquire()
        except Timeout:
            raise Conflict(
                f"{spec.name} is being installed by another DocBox process; wait for it."
            ) from None
        held.callback(lock.release)


def remove_engine(extra: str) -> EngineRemoveResult:
    if extra not in runtime.EXTRAS:
        raise NotFound(f"Unknown engine: {extra}")
    specs = _engine_specs(extra)
    with ExitStack() as held:
        _hold_model_locks(held, specs)
        engine_cache.evict_all({spec.id for spec in specs})
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
        raise Failed(str(exc)) from None
    return EngineRemoveResult(removed=True, pending_restart=False,
                              detail=f"{label} and its models were removed.")


# --- graphics-card builds ----------------------------------------------------------------

# Room the graphics-card build takes once unpacked, for every MB it downloads.
_UNPACKED_PER_DOWNLOADED = 2


def _build_job_key(extra: str) -> str:
    # Build switches are tracked by the job store like model installs, under their own key.
    return f"engine:{extra}"


def _status(job) -> DownloadStatus:
    return DownloadStatus(
        job_id=job.job_id, model_id=job.model_id, state=job.state,
        progress_pct=job.progress_pct, message=job.message,
    )


def _pending_build(extra: str) -> bool:
    """A switch waiting for a restart: state.json names the other build."""
    state = runtime.read_state()
    if not state.get("resync_pending"):
        return False
    wanted = set(state.get("extras", []))
    current = runtime.build_of(extra)
    if current is None:
        return False
    other = extra if current == "gpu" else runtime.GPU_BUILDS[extra]
    return other in wanted


def _gpu_blocked(extra: str, supported: gpu.Support, taken: str | None) -> str | None:
    """Why the engine can't switch to its graphics-card build now, or None."""
    if not supported.usable:
        return supported.reason
    if not runtime.can_install():
        return "DocBox can't change its packages here (no `uv` available)."
    if taken and taken != extra:
        return (f"{runtime.EXTRAS[taken][0]} uses the graphics card, and only one engine can. "
                "Switch it back to the processor first.")
    need_gb = runtime.gpu_download_mb(extra) * _UNPACKED_PER_DOWNLOADED / 1024
    free_gb = device.get_device_capabilities().disk_free_gb
    if free_gb < need_gb:
        return f"Needs about {need_gb:.0f} GB of free disk, and {free_gb:.0f} GB is free."
    return None


def gpu_status() -> GpuStatus:
    nvidia = device.nvidia_gpu()
    supported = gpu.support()
    builds = {extra: runtime.build_of(extra) for extra in runtime.GPU_BUILDS}
    taken = next((e for e, b in builds.items() if b == "gpu"), None)
    engines = []
    for extra, build in builds.items():
        job = job_store.unfinished_for(_build_job_key(extra))
        engines.append(EngineGpuBuild(
            id=extra,
            name=runtime.EXTRAS[extra][0],
            installed=build,
            gpu_download_mb=runtime.gpu_download_mb(extra),
            blocked=None if build == "gpu" else _gpu_blocked(extra, supported, taken),
            pending_restart=_pending_build(extra),
            job=_status(job) if job else None,
        ))
    return GpuStatus(
        usable=supported.usable,
        reason=supported.reason,
        name=nvidia.name if nvidia else None,
        driver_version=nvidia.driver_version if nvidia else None,
        cuda_version=nvidia.cuda_version if nvidia else None,
        cuda_required=gpu.CUDA_REQUIRED,
        compute_capability=nvidia.compute_capability if nvidia else None,
        memory_total_gb=nvidia.memory_gb if nvidia else None,
        memory_free_gb=device.gpu_free_memory_gb() if nvidia else None,
        engines=engines,
    )


def _check_switch(extra: str, build: str) -> None:
    if extra not in runtime.GPU_BUILDS:
        raise NotFound(f"No graphics-card build for engine: {extra}")
    if build not in ("cpu", "gpu"):
        raise Invalid(f"Unknown build: {build}")
    if build == "gpu" and runtime.build_of(extra) != "gpu":
        builds = {e: runtime.build_of(e) for e in runtime.GPU_BUILDS}
        taken = next((e for e, b in builds.items() if b == "gpu"), None)
        reason = _gpu_blocked(extra, gpu.support(), taken)
        if reason:
            raise Invalid(reason)


def switch_build(
    extra: str, build: str, progress: Callable[[float, str], None] | None = None,
) -> str:
    """Install the engine's graphics-card ("gpu") or CPU build in place of the other, on the
    calling thread. Returns what happened, in a sentence: a switch of an engine that's
    loaded in this process waits for a restart."""
    _check_switch(extra, build)
    specs = _engine_specs(extra)
    label = runtime.EXTRAS[extra][0]
    with ExitStack() as held:
        _hold_model_locks(held, specs)
        engine_cache.evict_all({spec.id for spec in specs})
        try:
            runtime.switch_build(extra, build, progress or (lambda *_: None))
        except runtime.RemovalNeedsRestart as exc:
            return str(exc)
        except runtime.EngineInstallError as exc:
            raise Failed(str(exc)) from None
    gpu.clear_fallbacks()
    where = "the graphics card" if build == "gpu" else "the processor"
    return f"{label} now reads on {where}."


def start_switch_build(
    extra: str, build: str, run_in_background: Callable[[Callable[[], None]], None] | None = None,
) -> DownloadStatus:
    """switch_build() on a background job; poll it with build_status(). Refuses at once
    what switch_build would."""
    _check_switch(extra, build)
    _engine_specs(extra)
    key = _build_job_key(extra)
    active = job_store.active_for(key)
    if active is not None:
        return _status(active)
    job = job_store.create(key)

    def work() -> None:
        def progress(pct: float, message: str) -> None:
            job_store.update(job.job_id, state="installing", progress_pct=pct, message=message)

        try:
            detail = switch_build(extra, build, progress)
            job_store.update(job.job_id, state="done", progress_pct=100.0, message=detail)
        except Exception as exc:  # noqa: BLE001 — reported on the job, polled by the caller
            job_store.update(job.job_id, state="error", message=getattr(exc, "detail", str(exc)))

    if run_in_background is None:
        threading.Thread(target=work, name=f"docbox-build-{extra}", daemon=True).start()
    else:
        run_in_background(work)
    return _status(job)


def build_status(job_id: str) -> DownloadStatus:
    job = job_store.get(job_id)
    if job is None or not job.model_id.startswith("engine:"):
        raise NotFound(f"Unknown engine job: {job_id}")
    return _status(job)
