"""Whether DocBox's own engines read on an NVIDIA graphics card, and which models do.

Three things decide it, and the model's `InferenceDevice` says which one didn't:

- this computer (`support()`): Windows or Linux on x86_64, an NVIDIA card whose driver runs
  CUDA 12.6 (the build `core/runtime.py` installs) and that build has kernels for;
- the engine's packages: its graphics-card build (`runtime.GPU_BUILDS`), which the user
  installs from Device, not the CPU build every engine starts with;
- the settings (`config_store`): "auto" (the default) puts the models whose
  `preferred_device` is "gpu" on the card, "gpu" every model of an engine that has the
  build, "cpu" none; a model's own setting wins over the global one.

Then, as a model loads: enough free graphics memory (`choose`), and CUDA starting. When it
doesn't, the engine reads on the processor and `record_fallback` keeps why, which the
model's note shows until it loads on the card again.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass

from docbox.backend.core import config_store, device, runtime
from docbox.backend.core.registry import ModelSpec
from docbox.backend.schemas import Device, DevicePreference

CUDA_REQUIRED = "12.6"
# Compute capabilities the CUDA 12.6 builds of Paddle 3.2 and torch have kernels for:
# Pascal (6.0) up to Hopper (9.0). Blackwell cards (RTX 50 series, 12.0) need CUDA 12.8+.
_MIN_COMPUTE = (6, 0)
_MAX_COMPUTE = (9, 0)
# Graphics memory left over for the display and other programs.
_VRAM_MARGIN_MB = 512


def _version(text: str | None) -> tuple[int, ...] | None:
    try:
        return tuple(int(p) for p in (text or "").split(".")) or None
    except ValueError:
        return None


@dataclass(frozen=True)
class Support:
    usable: bool
    # Why not, when it isn't.
    reason: str | None = None


def support(
    gpu: device.NvidiaGpu | None = None,
    *,
    platform_ok: bool | None = None,
) -> Support:
    """Whether this computer can run the graphics-card builds (not whether they're
    installed). Arguments are for tests; by default it looks at this computer."""
    if platform_ok is None:
        platform_ok = runtime.gpu_builds_supported()
    if not platform_ok:
        where = "macOS" if sys.platform == "darwin" else "this system"
        return Support(False, f"DocBox's engines read on the processor on {where}.")
    gpu = gpu if gpu is not None else device.nvidia_gpu()
    if gpu is None:
        return Support(False, "No NVIDIA graphics card with its driver installed was found.")
    cuda = _version(gpu.cuda_version)
    if cuda is not None and cuda < _version(CUDA_REQUIRED):
        return Support(
            False,
            f"The graphics driver ({gpu.driver_version or 'installed'}) runs CUDA "
            f"{gpu.cuda_version}; DocBox needs CUDA {CUDA_REQUIRED}. Update the NVIDIA driver.",
        )
    cap = _version(gpu.compute_capability)
    if cap is not None and cap < _MIN_COMPUTE:
        return Support(False, f"The {gpu.name} is too old for DocBox's CUDA {CUDA_REQUIRED} build.")
    if cap is not None and cap[:2] > _MAX_COMPUTE:
        return Support(
            False,
            f"DocBox's CUDA {CUDA_REQUIRED} build doesn't support the {gpu.name} yet.",
        )
    return Support(True)


@dataclass(frozen=True)
class Choice:
    device: Device
    setting: DevicePreference
    # Why it reads on the processor when the card could have been used, else None.
    note: str | None = None


def setting_for(model_id: str) -> DevicePreference:
    return config_store.get_model_devices().get(model_id) or config_store.get_device_preference()


def gpu_capable(spec: ModelSpec) -> bool:
    """Whether the model's engine has a graphics-card build."""
    return spec.requires_extra in runtime.GPU_BUILDS


def choose(
    spec: ModelSpec,
    *,
    setting: DevicePreference,
    supported: Support,
    gpu_build: bool,
    free_gb: float | None,
    fallback: str | None = None,
) -> Choice:
    """Where `spec` reads, given everything that decides it (see the module docstring).
    Pure, so tests can walk every case."""
    if not gpu_capable(spec):
        return Choice("cpu", setting)
    wants_gpu = setting == "gpu" or (setting == "auto" and spec.preferred_device == "gpu")
    if not wants_gpu:
        return Choice("cpu", setting)
    if not supported.usable:
        # Nothing to do about it here: say so only when the model was set to the card.
        return Choice("cpu", setting, supported.reason if setting == "gpu" else None)
    if not gpu_build:
        return Choice(
            "cpu", setting,
            "Install the graphics-card build of its engine under Device to read it there.",
        )
    needed_mb = spec.approx_ram_mb + _VRAM_MARGIN_MB
    if free_gb is not None and free_gb * 1024 < needed_mb:
        return Choice(
            "cpu", setting,
            f"Needs about {needed_mb / 1024:.1f} GB of graphics memory and {free_gb:.1f} GB "
            "is free, so it reads on the processor.",
        )
    if fallback:
        return Choice("cpu", setting, fallback)
    return Choice("gpu", setting)


def device_for(spec: ModelSpec, *, free_gb: float | None = None) -> Choice:
    """Where `spec` reads on this computer right now."""
    if not gpu_capable(spec):
        return Choice("cpu", setting_for(spec.id))
    supported = support()
    gpu_build = runtime.build_of(spec.requires_extra) == "gpu"
    if free_gb is None and supported.usable and gpu_build:
        free_gb = device.gpu_free_memory_gb()
    return choose(
        spec,
        setting=setting_for(spec.id),
        supported=supported,
        gpu_build=gpu_build,
        free_gb=free_gb,
        fallback=fallback_for(spec.id),
    )


# Models that were to read on the card but couldn't (CUDA didn't start, ran out of graphics
# memory), with why. They stay on the processor until DocBox restarts or the device
# settings or the engine's build change (clear_fallbacks), rather than fail again each load.
_fallbacks: dict[str, str] = {}
_fallbacks_lock = threading.Lock()


def record_fallback(model_id: str, reason: str | None) -> None:
    with _fallbacks_lock:
        if reason:
            _fallbacks[model_id] = reason
        else:
            _fallbacks.pop(model_id, None)


def clear_fallbacks() -> None:
    with _fallbacks_lock:
        _fallbacks.clear()


def fallback_for(model_id: str) -> str | None:
    with _fallbacks_lock:
        return _fallbacks.get(model_id)


def fallback_message(exc: BaseException) -> str:
    """A sentence for a model that couldn't start or keep reading on the card."""
    text = str(exc).strip().splitlines()[0][:200] if str(exc).strip() else type(exc).__name__
    if "out of memory" in text.lower():
        return "Ran out of graphics memory, so it reads on the processor."
    return f"The graphics card couldn't be used ({text}), so it reads on the processor."


def is_out_of_memory(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "out of memory" in text or "resourceexhausted" in text.replace(" ", "")


def load(spec: ModelSpec, engine) -> Device:
    """Load `engine` on the device `spec` reads on here, and say which. An engine with a
    graphics-card build has `use_device()`; when it fails to load on the card, it loads on
    the processor instead and the model's note says why."""
    use_device = getattr(engine, "use_device", None)
    if use_device is None or not gpu_capable(spec):
        engine.load()
        return "cpu"
    choice = device_for(spec)
    use_device(choice.device)
    if choice.device == "cpu":
        engine.load()
        return "cpu"
    try:
        engine.load()
    except Exception as exc:  # noqa: BLE001 — whatever CUDA or the engine's library raised
        record_fallback(spec.id, fallback_message(exc))
        use_device("cpu")
        engine.load()
        return "cpu"
    record_fallback(spec.id, None)
    return "gpu"
