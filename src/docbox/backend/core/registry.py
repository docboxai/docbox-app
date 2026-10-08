"""Registry of installable OCR models plus a hardware-fit check."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import IntEnum

from docbox.backend.engines.base import OCREngine
from docbox.backend.schemas import DeviceCapabilities, FitResult

# Leave headroom for the OS and other apps rather than judging fit against 100% of
# available RAM.
_RAM_SAFETY_MARGIN_MB = 512


class Tier(IntEnum):
    """How much computer a model needs to run without slowing everything else down."""

    LIGHT = 1
    STANDARD = 2
    HEAVY = 3


# (total RAM in GB, physical CPU cores) a computer needs for each tier: an "8 GB" and a
# "16 GB" computer, which report a little less once the graphics take their share. Total
# RAM rather than free RAM, so the pick doesn't flip whenever a browser tab opens;
# check_fit still covers what's free right now. Rules of thumb, not measurements: a
# standard model takes about 1.5 GB and keeps 4 cores busy while it reads.
_TIER_NEEDS: dict[Tier, tuple[float, int]] = {
    Tier.LIGHT: (0, 1),
    Tier.STANDARD: (7, 4),
    Tier.HEAVY: (14, 8),
}


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
    # A large vision model that is slow on a CPU. DocBox's own engines always run on the
    # CPU; `runs_on_gpu` marks engines that use a graphics card by themselves (Ollama).
    slow_on_cpu: bool = False
    runs_on_gpu: bool = False
    tier: Tier = Tier.LIGHT
    # How well it reads everyday documents, against the other built-in models (higher is
    # better). None: never picked as the recommendation, e.g. a model for one language
    # family, or one from Ollama or the cloud.
    quality: int | None = None
    # Sizes of one model: specs sharing a `family` are the same model at different sizes
    # ("PaddleOCR — English": Mobile, Large), so the benchmark graph joins them with a
    # line. `variant` names this size. None: the model stands alone.
    family: str | None = None
    variant: str | None = None


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


def _has_dedicated_gpu(caps: DeviceCapabilities) -> bool:
    return bool(caps.gpu_name) and not caps.gpu_name.startswith(("Intel", "Microsoft Basic"))


def _slow_here(spec: ModelSpec, caps: DeviceCapabilities) -> bool:
    return spec.slow_on_cpu and not (spec.runs_on_gpu and _has_dedicated_gpu(caps))


def check_fit(spec: ModelSpec, caps: DeviceCapabilities) -> FitResult:
    reasons: list[str] = []
    summary: str | None = None
    available_mb = caps.ram_available_gb * 1024
    needed_mb = spec.approx_ram_mb + _RAM_SAFETY_MARGIN_MB
    if available_mb < needed_mb:
        reasons.append(
            f"Needs ~{needed_mb:.0f} MB free RAM, only {available_mb:.0f} MB available"
        )
        summary = f"Needs {math.ceil(needed_mb / 1024)} GB free RAM"
    disk_free_mb = caps.disk_free_gb * 1024
    if disk_free_mb < spec.min_disk_mb:
        reasons.append(
            f"Needs ~{spec.min_disk_mb} MB free disk, only {disk_free_mb:.0f} MB available"
        )
        summary = summary or f"Needs {math.ceil(spec.min_disk_mb / 1024)} GB free disk"

    notes: list[str] = []
    if _slow_here(spec, caps):
        notes.append("Slow without a GPU")

    return FitResult(
        fits=not reasons,
        reasons=reasons,
        notes=notes,
        summary=summary or (notes[0] if notes else "Runs well"),
    )


def runs_smoothly(spec: ModelSpec, caps: DeviceCapabilities) -> bool:
    """Whether this computer clears the model's tier, has the memory and disk for it
    right now, and runs it at full speed (no "slow without a GPU")."""
    ram_gb, cores = _TIER_NEEDS[spec.tier]
    fit = check_fit(spec, caps)
    return (
        caps.ram_total_gb >= ram_gb
        and caps.cpu_physical_cores >= cores
        and fit.fits
        and not fit.notes
    )


def recommend(specs: Iterable[ModelSpec], caps: DeviceCapabilities) -> ModelSpec | None:
    """The best-reading model that runs smoothly here, or None if none does. Quality
    decides, not tier: a heavier model is only worth it when it also reads better. On a
    tie the first one listed wins, so the pick is stable."""
    candidates = [s for s in specs if s.quality is not None and runs_smoothly(s, caps)]
    # max() keeps the first of equal items.
    return max(candidates, key=lambda s: s.quality or 0, default=None)
