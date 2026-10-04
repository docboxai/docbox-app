"""Pydantic models shared between backend routes and the GUI's API client."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: Literal["ok"] = "ok"


class DeviceCapabilities(BaseModel):
    ram_total_gb: float
    ram_available_gb: float
    cpu_physical_cores: int
    cpu_logical_cores: int
    disk_free_gb: float
    disk_total_gb: float
    # The main graphics card, for display; DocBox's own engines run on the CPU either way.
    gpu_name: str | None = None
    os_name: str
    arch: str


class FitResult(BaseModel):
    fits: bool
    # Hard blockers: not enough RAM or disk.
    reasons: list[str] = []
    # Soft warnings that don't stop it running (e.g. a big vision model on a CPU).
    notes: list[str] = []
    # One short phrase for tables and chips: "Runs well", "Needs 8 GB free RAM", ...
    summary: str = "Runs well"


# What one click on a model will do:
# ready             -> nothing; it can run now
# needs_download    -> download the weights
# needs_engine      -> install the engine's packages, then download the weights
# needs_prerequisite-> the user must install/start an external program first (Ollama, Tesseract)
ModelStatus = Literal["ready", "needs_download", "needs_engine", "needs_prerequisite"]


# "paused": the user paused it; starting the download again resumes it.
DownloadState = Literal["pending", "installing", "downloading", "paused", "done", "error"]


class DownloadStartResponse(BaseModel):
    job_id: str


class DownloadStatus(BaseModel):
    job_id: str
    model_id: str
    state: DownloadState
    progress_pct: float | None = None
    message: str | None = None


class ModelInfo(BaseModel):
    id: str
    name: str
    engine: str
    description: str
    languages: list[str]
    approx_download_mb: int
    approx_ram_mb: int
    min_disk_mb: int
    downloaded: bool
    engine_installed: bool
    status: ModelStatus
    requires_extra: str | None = None
    prerequisite: str | None = None
    fit: FitResult
    # The model's unfinished (running or paused) download, so the UI can show progress
    # after the user navigates away and back.
    active_job: DownloadStatus | None = None


class OcrLine(BaseModel):
    text: str
    confidence: float | None = None
    # [left, top, right, bottom] in the page image's pixels, for engines that report
    # positions; used to place the invisible text layer of a searchable PDF.
    box: list[float] | None = None


class OcrResult(BaseModel):
    model_id: str
    lines: list[OcrLine]
    text: str


class PlatformStatus(BaseModel):
    id: str
    name: str
    available: bool
    detail: str | None = None


class NvidiaApiKeyRequest(BaseModel):
    api_key: str


class NvidiaApiKeyStatus(BaseModel):
    configured: bool


class PrerequisiteInfo(BaseModel):
    id: str
    name: str
    about: str
    state: Literal["ready", "installed", "missing"]
    can_auto_install: bool
    can_start: bool
    commands: list[str]
    download_url: str


class EngineStorage(BaseModel):
    id: str
    name: str
    installed: bool
    can_install: bool
    package_bytes: int
    model_bytes: int
    models_downloaded: int
    removal_pending: bool


class StorageInfo(BaseModel):
    data_dir: str
    # Everything under the models dir: every engine's weights plus Tesseract's language
    # files. Ollama keeps its models in its own store, so they aren't counted.
    models_bytes: int
    engines: list[EngineStorage]


class EngineRemoveResult(BaseModel):
    removed: bool
    pending_restart: bool
    detail: str


class Settings(BaseModel):
    default_model_id: str | None
    cloud_enabled: bool
    output_dir: str


class SettingsUpdate(BaseModel):
    # Fields left out are unchanged; default_model_id="" clears the default.
    default_model_id: str | None = None
    cloud_enabled: bool | None = None


OutputFormat = Literal["txt", "md", "pdf", "json"]
ReadState = Literal["queued", "reading", "done", "error", "cancelled"]


class ReadSummary(BaseModel):
    """One file read, as listed under Recent files."""

    id: str
    file_name: str
    model_id: str
    model_name: str
    output_format: OutputFormat
    state: ReadState
    pages_total: int | None = None
    pages_done: int = 0
    seconds: float | None = None
    created_at: float
    output_path: str | None = None
    error: str | None = None


class ReadPage(BaseModel):
    lines: list[OcrLine]
    text: str


class ReadDetail(ReadSummary):
    pages: list[ReadPage] = []
    text: str = ""


class ReadStartResponse(BaseModel):
    reads: list[ReadSummary]
