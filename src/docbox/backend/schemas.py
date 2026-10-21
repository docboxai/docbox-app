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
    # An NVIDIA card's memory, from nvidia-smi; None for other cards or no driver.
    gpu_memory_gb: float | None = None
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


Device = Literal["cpu", "gpu"]
# Where the user wants models to read (settings): "auto" puts the models that read best on
# a graphics card there, when this computer can (core/gpu.py).
DevicePreference = Literal["auto", "cpu", "gpu"]


class InferenceDevice(BaseModel):
    # Where this model reads on this computer.
    runs_on: Device
    # The setting deciding it: this model's own, else the global one.
    setting: DevicePreference = "auto"
    # Whether its engine has a graphics-card build DocBox can install (PaddleOCR, EasyOCR).
    gpu_capable: bool = False
    # Where it reads best: "gpu" for models a graphics card makes several times faster,
    # "cpu" for ones that are already quick on the processor.
    preferred: Device
    # How many times faster it reads on a graphics card, from the model's published timings.
    gpu_speedup: float | None = None
    # One sentence on what would make it faster here, or None when it's already at its best.
    note: str | None = None


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
    # The most memory it takes while reading a page.
    approx_ram_mb: int
    # True when approx_ram_mb and cpu_page_seconds were measured, not estimated.
    ram_measured: bool = False
    # Seconds to read a full page on the processor, measured (models_catalog.py says where).
    cpu_page_seconds: float | None = None
    # Where the published figures (sizes, speeds) come from.
    figures_source: str | None = None
    min_disk_mb: int
    device: InferenceDevice
    downloaded: bool
    engine_installed: bool
    status: ModelStatus
    requires_extra: str | None = None
    prerequisite: str | None = None
    fit: FitResult
    # The one model Setup recommends: the best-reading built-in model that runs smoothly
    # on this computer (registry.recommend).
    recommended: bool = False
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


class EngineGpuBuild(BaseModel):
    # The engine (pyproject extra of its CPU build: "paddle", "easyocr").
    id: str
    name: str
    # Which build is installed; None: the engine isn't installed.
    installed: Device | None
    # Download size of the graphics-card build's packages on this system.
    gpu_download_mb: int
    # Why it can't switch now (another engine has the card, no uv, ...), or None.
    blocked: str | None = None
    # A switch that waits for DocBox to restart (the engine was in use).
    pending_restart: bool = False
    # The running or last switch, polled like a model install.
    job: DownloadStatus | None = None


class GpuStatus(BaseModel):
    """Whether DocBox's own engines can read on this computer's graphics card."""

    usable: bool
    # Why not, in a sentence, when it isn't.
    reason: str | None = None
    name: str | None = None
    driver_version: str | None = None
    # The newest CUDA the driver runs, and the one DocBox's graphics-card builds need.
    cuda_version: str | None = None
    cuda_required: str
    compute_capability: str | None = None
    memory_total_gb: float | None = None
    memory_free_gb: float | None = None
    engines: list[EngineGpuBuild] = []


class EngineBuildRequest(BaseModel):
    build: Device


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
    # The most memory a model may take while reading; None: no limit beyond what's free.
    ram_limit_gb: float | None = None
    # Where models read (core/gpu.py), and models set otherwise than that.
    device_preference: DevicePreference = "auto"
    model_devices: dict[str, Device] = {}


class SettingsUpdate(BaseModel):
    # Fields left out are unchanged; default_model_id="" clears the default.
    default_model_id: str | None = None
    cloud_enabled: bool | None = None
    # 0 removes the limit.
    ram_limit_gb: float | None = None
    device_preference: DevicePreference | None = None
    # Merged into the saved ones; "auto" makes a model follow device_preference again.
    model_devices: dict[str, DevicePreference] | None = None


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
    # The process doing the read (the app's backend, the CLI or the MCP server share history).
    pid: int | None = None


class ReadPage(BaseModel):
    lines: list[OcrLine]
    text: str
    # "pdf_text": the PDF page carried its own text, used as-is instead of OCR.
    source: Literal["ocr", "pdf_text"] = "ocr"


class ReadDetail(ReadSummary):
    pages: list[ReadPage] = []
    text: str = ""


class ReadStartResponse(BaseModel):
    reads: list[ReadSummary]
