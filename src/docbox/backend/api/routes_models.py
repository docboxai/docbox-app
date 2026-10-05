from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response

from docbox.backend import platforms
from docbox.backend.core import prerequisites, runtime
from docbox.backend.core.device import get_device_capabilities
from docbox.backend.core.jobs import DownloadJob, JobPaused, job_store
from docbox.backend.core.registry import ModelSpec, check_fit, recommend, registry
from docbox.backend.engines.base import NotDeletableError, ProgressCallback
from docbox.backend.engines.remote_engine import EngineServiceError
from docbox.backend.schemas import (
    DownloadStartResponse,
    DownloadStatus,
    ModelInfo,
)

router = APIRouter(prefix="/api/models", tags=["models"])


class _Snapshot:
    """Engine/prerequisite state computed once per request, not once per model — a
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
        active_job=_job_status(job) if (job := job_store.unfinished_for(spec.id)) else None,
    )


def _job_status(job: DownloadJob) -> DownloadStatus:
    return DownloadStatus(
        job_id=job.job_id,
        model_id=job.model_id,
        state=job.state,
        progress_pct=job.progress_pct,
        message=job.message,
    )


def _resolve(model_id: str) -> ModelSpec:
    try:
        return platforms.resolve_spec(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}") from None


@router.get("", response_model=list[ModelInfo])
def list_models() -> list[ModelInfo]:
    snap = _Snapshot()
    specs = [*registry.list(), *platforms.list_dynamic_specs()]
    return [_to_model_info(spec, snap) for spec in specs]


@router.get("/{model_id}", response_model=ModelInfo)
def get_model(model_id: str) -> ModelInfo:
    return _to_model_info(_resolve(model_id), _Snapshot())


def _scaled(job_id: str, state: str, lo: float, hi: float) -> ProgressCallback:
    def cb(pct: float, message: str) -> None:
        # At 100% the files are already in place; pausing then would report a finished
        # download as paused.
        if pct < 100 and job_store.pause_requested(job_id):
            raise JobPaused
        job_store.update(
            job_id, state=state, progress_pct=lo + (hi - lo) * pct / 100.0, message=message
        )

    return cb


def _run_download(job_id: str, model_id: str) -> None:
    """One job, two stages: install the engine's packages if missing (0-40%), then
    download the model's weights (40-100%, or 0-100% when the engine is already there)."""
    try:
        spec = platforms.resolve_spec(model_id)
        weights_from = 0.0
        if spec.requires_extra and not runtime.extra_installed(spec.requires_extra):
            label = runtime.EXTRAS[spec.requires_extra][0]
            job_store.update(job_id, state="installing", progress_pct=0.0,
                             message=f"installing {label}")
            runtime.ensure_extra(spec.requires_extra, _scaled(job_id, "installing", 0, 40))
            weights_from = 40.0

        job_store.update(job_id, state="downloading", progress_pct=weights_from,
                         message="starting download")
        spec.engine_factory().download(_scaled(job_id, "downloading", weights_from, 100))
        job_store.update(job_id, state="done", progress_pct=100.0, message="ready")
    except JobPaused:
        job_store.update(job_id, state="paused", message="paused")
    except Exception as exc:  # noqa: BLE001
        job_store.update(job_id, state="error", message=str(exc))


@router.post("/{model_id}/download", response_model=DownloadStartResponse, status_code=202)
def start_download(model_id: str, background_tasks: BackgroundTasks) -> DownloadStartResponse:
    spec = _resolve(model_id)

    # A second click while it's already going rejoins the running job instead of
    # starting a duplicate download into the same files.
    active = job_store.active_for(model_id)
    if active is not None:
        return DownloadStartResponse(job_id=active.job_id)

    if spec.prerequisite and not prerequisites.is_satisfied(spec.prerequisite):
        name = prerequisites.PREREQUISITES[spec.prerequisite]["name"]
        raise HTTPException(
            status_code=409, detail=f"{name} needs to be installed and running first."
        )

    paused = job_store.unfinished_for(model_id)
    job = job_store.create(model_id, progress_pct=(paused.progress_pct or 0.0) if paused else 0.0)
    background_tasks.add_task(_run_download, job.job_id, model_id)
    return DownloadStartResponse(job_id=job.job_id)


@router.get("/{model_id}/download/status", response_model=DownloadStatus)
def download_status(model_id: str, job_id: str) -> DownloadStatus:
    job = job_store.get(job_id)
    if job is None or job.model_id != model_id:
        raise HTTPException(status_code=404, detail=f"Unknown download job: {job_id}")
    return _job_status(job)


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
    return _job_status(job)


@router.delete("/{model_id}", status_code=204)
def delete_model(model_id: str) -> Response:
    spec = _resolve(model_id)
    if job_store.active_for(model_id) is not None:
        raise HTTPException(status_code=409, detail="This model is downloading; wait for it.")
    job_store.discard_paused(model_id)
    try:
        spec.engine_factory().delete()
    except NotDeletableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except EngineServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return Response(status_code=204)
