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


class FitResult(BaseModel):
    fits: bool
    reasons: list[str] = []


# What one click on a model will do:
# ready             -> nothing; it can run now
# needs_download    -> download the weights
# needs_engine      -> install the engine's packages, then download the weights
# needs_prerequisite-> the user must install/start an external program first (Ollama, Tesseract)
ModelStatus = Literal["ready", "needs_download", "needs_engine", "needs_prerequisite"]


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


DownloadState = Literal["pending", "installing", "downloading", "done", "error"]


class DownloadStartResponse(BaseModel):
    job_id: str


class DownloadStatus(BaseModel):
    job_id: str
    model_id: str
    state: DownloadState
    progress_pct: float | None = None
    message: str | None = None


class OcrLine(BaseModel):
    text: str
    confidence: float | None = None


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
    engines: list[EngineStorage]


class EngineRemoveResult(BaseModel):
    removed: bool
    pending_restart: bool
    detail: str
