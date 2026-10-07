"""The model catalog as every front end sees it: listing with install status and fit,
installing (engine packages, then weights) and removing."""

from __future__ import annotations

from collections.abc import Callable

import docbox.backend.models_catalog  # noqa: F401 — importing it fills the registry
from docbox.backend import platforms
from docbox.backend.core import locks, prerequisites, runtime
from docbox.backend.core.device import get_device_capabilities
from docbox.backend.core.jobs import DownloadJob, JobPaused, job_store
from docbox.backend.core.registry import ModelSpec, check_fit, recommend, registry
from docbox.backend.engines.base import NotDeletableError, ProgressCallback
from docbox.backend.engines.remote_engine import EngineServiceError
from docbox.backend.schemas import DownloadStatus, ModelInfo
from docbox.service.errors import (
    Blocked,
    Conflict,
    Failed,
    Invalid,
    NeedsPrerequisite,
    NotFound,
    ServiceError,
)

# (state, overall percent 0-100, message): state is "installing" while the engine's
# packages go in, "downloading" while the weights come down.
InstallProgress = Callable[[str, float, str], None]


class _Snapshot:
    """Engine/prerequisite state computed once per listing, not once per model — a
    prerequisite check can be a network call (Ollama), and the listing has many models."""

    def __init__(self) -> None:
        self.caps = get_device_capabilities()
        self.extras = runtime.installed_extras()
        self._prereqs: dict[str, bool] = {}
        # Only the built-in catalog is ranked; Ollama and cloud models never are.
        pick = recommend(registry.list(), self.caps)
        self.recommended_id = pick.id if pick else None

    def prereq_ok(self, prereq_id: str) -> bool:
        if prereq_id not in self._prereqs:
            self._prereqs[prereq_id] = prerequisites.is_satisfied(prereq_id)
        return self._prereqs[prereq_id]


def job_status(job: DownloadJob) -> DownloadStatus:
    return DownloadStatus(
        job_id=job.job_id,
        model_id=job.model_id,
        state=job.state,
        progress_pct=job.progress_pct,
        message=job.message,
    )


def _to_model_info(spec: ModelSpec, snap: _Snapshot) -> ModelInfo:
    engine_installed = spec.requires_extra is None or spec.requires_extra in snap.extras
    downloaded = False
    if engine_installed:
        try:
            downloaded = spec.engine_factory().is_downloaded()
        except EngineServiceError:
            # One engine container being down shouldn't break the whole listing; running
            # or downloading that model will report the outage explicitly (503).
            downloaded = False

    if not engine_installed:
        status = "needs_engine"
    elif spec.prerequisite and not snap.prereq_ok(spec.prerequisite):
        status = "needs_prerequisite"
    elif downloaded:
        status = "ready"
    else:
        status = "needs_download"

    return ModelInfo(
        id=spec.id,
        name=spec.name,
        engine=spec.engine,
        description=spec.description,
        languages=spec.languages,
        approx_download_mb=spec.approx_download_mb,
        approx_ram_mb=spec.approx_ram_mb,
        min_disk_mb=spec.min_disk_mb,
        downloaded=downloaded,
        engine_installed=engine_installed,
        status=status,
        requires_extra=spec.requires_extra,
        prerequisite=spec.prerequisite,
        fit=check_fit(spec, snap.caps),
        recommended=spec.id == snap.recommended_id,
        active_job=job_status(job) if (job := job_store.unfinished_for(spec.id)) else None,
    )


def resolve(model_id: str) -> ModelSpec:
    if platforms.cloud_blocked(model_id):
        raise Blocked("The cloud engine is switched off")
    try:
        return platforms.resolve_spec(model_id)
    except KeyError:
        raise NotFound(f"Unknown model: {model_id}") from None


def list_models() -> list[ModelInfo]:
    snap = _Snapshot()
    specs = [*registry.list(), *platforms.list_dynamic_specs()]
    return [_to_model_info(spec, snap) for spec in specs]


def get_model(model_id: str) -> ModelInfo:
    try:
        spec = platforms.resolve_spec(model_id)
    except KeyError:
        raise NotFound(f"Unknown model: {model_id}") from None
    return _to_model_info(spec, _Snapshot())


def check_installable(model_id: str) -> ModelSpec:
    """The model's spec if installing it can start now; otherwise why not."""
    spec = resolve(model_id)
    if spec.prerequisite and not prerequisites.is_satisfied(spec.prerequisite):
        name = prerequisites.PREREQUISITES[spec.prerequisite]["name"]
        raise NeedsPrerequisite(f"{name} needs to be installed and running first.")
    return spec


def install_model(
    model_id: str,
    progress: InstallProgress | None = None,
    should_pause: Callable[[], bool] | None = None,
) -> None:
    """Install everything a model needs, on the calling thread: the engine's packages if
    missing (0-40%), then the weights (40-100%, or 0-100% when the engine is already
    there). `should_pause` is asked at each progress report; when it says yes the install
    stops by raising JobPaused (installing again resumes). Another DocBox process
    installing the same model makes this raise Conflict."""
    spec = check_installable(model_id)
    lock = locks.model_lock(spec.id)
    try:
        lock.acquire()
    except locks.Timeout:
        raise Conflict(f"{spec.name} is already being installed by another DocBox window") from None
    try:
        _install(spec, progress or (lambda *_: None), should_pause or (lambda: False))
    except (JobPaused, ServiceError, KeyboardInterrupt):
        raise
    except EngineServiceError as exc:
        raise ServiceError(exc.detail, status=exc.status_code) from None
    except Exception as exc:
        raise Failed(str(exc)) from exc
    finally:
        lock.release()


def stage_progress(
    state: str, lo: float, hi: float,
    progress: InstallProgress, should_pause: Callable[[], bool],
) -> ProgressCallback:
    """An engine's 0-100 progress callback for one stage, mapped into [lo, hi] overall."""

    def cb(pct: float, message: str) -> None:
        # At 100% the files are already in place; pausing then would report a finished
        # download as paused.
        if pct < 100 and should_pause():
            raise JobPaused
        progress(state, lo + (hi - lo) * pct / 100.0, message)

    return cb


def _install(spec: ModelSpec, progress: InstallProgress, should_pause: Callable[[], bool]):
    weights_from = 0.0
    if spec.requires_extra and not runtime.extra_installed(spec.requires_extra):
        label = runtime.EXTRAS[spec.requires_extra][0]
        progress("installing", 0.0, f"installing {label}")
        runtime.ensure_extra(
            spec.requires_extra, stage_progress("installing", 0, 40, progress, should_pause)
        )
        weights_from = 40.0

    progress("downloading", weights_from, "starting download")
    spec.engine_factory().download(
        stage_progress("downloading", weights_from, 100, progress, should_pause)
    )
    progress("done", 100.0, "ready")


def remove_model(model_id: str) -> None:
    try:
        spec = platforms.resolve_spec(model_id)
    except KeyError:
        raise NotFound(f"Unknown model: {model_id}") from None
    if job_store.active_for(model_id) is not None:
        raise Conflict("This model is downloading; wait for it.")
    lock = locks.model_lock(spec.id)
    try:
        lock.acquire()
    except locks.Timeout:
        raise Conflict(f"{spec.name} is being installed by another DocBox window") from None
    try:
        job_store.discard_paused(model_id)
        spec.engine_factory().delete()
    except NotDeletableError as exc:
        raise Invalid(str(exc)) from None
    except EngineServiceError as exc:
        raise ServiceError(exc.detail, status=exc.status_code) from None
    except RuntimeError as exc:
        raise ServiceError(str(exc), status=502) from None
    finally:
        lock.release()
