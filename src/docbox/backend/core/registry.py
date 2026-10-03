"""Registry of installable OCR models plus a hardware-fit check."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from docbox.backend.engines.base import OCREngine
from docbox.backend.schemas import DeviceCapabilities, FitResult

# Leave headroom for the OS and other apps rather than judging fit against 100% of
# available RAM.
_RAM_SAFETY_MARGIN_MB = 512


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    engine: str
    description: str
    languages: list[str]
    approx_download_mb: int
    approx_ram_mb: int
    min_disk_mb: int
    engine_factory: Callable[[], OCREngine]
    # pyproject extra holding this engine's packages (installed on demand, core/runtime.py)
    requires_extra: str | None = None
    # external program the user must have first: "tesseract" | "ollama" (core/prerequisites.py)
    prerequisite: str | None = None


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelSpec] = {}

    def register(self, spec: ModelSpec) -> None:
        self._models[spec.id] = spec

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self._models[model_id]
        except KeyError:
            raise KeyError(f"Unknown model id: {model_id}") from None

    def list(self) -> list[ModelSpec]:
        return list(self._models.values())


registry = ModelRegistry()


def check_fit(spec: ModelSpec, caps: DeviceCapabilities) -> FitResult:
    reasons: list[str] = []

    available_mb = caps.ram_available_gb * 1024
    needed_mb = spec.approx_ram_mb + _RAM_SAFETY_MARGIN_MB
    if available_mb < needed_mb:
        reasons.append(
            f"Needs ~{needed_mb:.0f} MB free RAM, only {available_mb:.0f} MB available"
        )

    disk_free_mb = caps.disk_free_gb * 1024
    if disk_free_mb < spec.min_disk_mb:
        reasons.append(
            f"Needs ~{spec.min_disk_mb} MB free disk, only {disk_free_mb:.0f} MB available"
        )

    return FitResult(fits=not reasons, reasons=reasons)
