"""Device hardware-capability detection (RAM / CPU / disk / graphics)."""

from __future__ import annotations

import functools
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

import psutil

from docbox.backend.core.paths import get_data_dir
from docbox.backend.schemas import DeviceCapabilities

_BYTES_PER_GB = 1024**3
_PROBE_TIMEOUT_S = 4.0
_CSV = "--format=csv,noheader,nounits"


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


@dataclass(frozen=True)
class NvidiaGpu:
    name: str
    memory_gb: float
    driver_version: str | None
    # The newest CUDA the driver runs, from nvidia-smi's banner ("12.6"); None if unknown.
    cuda_version: str | None
    # "8.6"; None when the driver is too old to report it.
    compute_capability: str | None


def _cuda_version() -> str | None:
    match = re.search(r"CUDA Version:\s*([\d.]+)", _run(["nvidia-smi"]) or "")
    return match.group(1) if match else None


@functools.lru_cache(maxsize=1)
def nvidia_gpu() -> NvidiaGpu | None:
    """The first NVIDIA card, when its driver is installed. Cached: it doesn't change while
    the app runs (its free memory does: gpu_free_memory_gb)."""
    if not shutil.which("nvidia-smi"):
        return None
    fields = "name,memory.total,driver_version"
    # compute_cap is newer than some drivers; without it the query fails as a whole.
    out = _run(["nvidia-smi", f"--query-gpu={fields},compute_cap", _CSV])
    with_cap = out is not None
    if out is None:
        out = _run(["nvidia-smi", f"--query-gpu={fields}", _CSV])
    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if with_cap:
            *parts, cap = parts
        else:
            cap = None
        name, memory_mb, driver = ", ".join(parts[:-2]), parts[-2], parts[-1]
        try:
            memory_gb = round(float(memory_mb) / 1024, 1)
        except ValueError:
            continue
        return NvidiaGpu(
            name=name, memory_gb=memory_gb, driver_version=driver or None,
            cuda_version=_cuda_version(),
            compute_capability=cap if cap and cap[0].isdigit() else None,
        )
    return None


def gpu_free_memory_gb() -> float | None:
    """The NVIDIA card's free memory right now, or None without one."""
    if nvidia_gpu() is None:
        return None
    out = _run(["nvidia-smi", "--query-gpu=memory.free", _CSV]) or ""
    try:
        return round(float(out.splitlines()[0]) / 1024, 2)
    except (IndexError, ValueError):
        return None


def _linux_gpu() -> str | None:
    if not shutil.which("lspci"):
        return None
    out = _run(["lspci", "-mm"]) or ""
    # Prefer a discrete card (anything not Intel's integrated graphics) when there are two.
    found: list[str] = []
    for line in out.splitlines():
        if not any(kind in line for kind in ('"VGA', '"3D', '"Display')):
            continue
        fields = line.split('"')
        if len(fields) >= 6:
            found.append(f"{fields[3]} {fields[5]}".strip())
    discrete = [g for g in found if not g.startswith("Intel")]
    return (discrete or found or [None])[0]


def _windows_gpu() -> str | None:
    out = _run([
        "powershell", "-NoProfile", "-Command",
        "(Get-CimInstance Win32_VideoController).Name",
    ]) or ""
    names = [line.strip() for line in out.splitlines() if line.strip()]
    discrete = [n for n in names if not n.startswith(("Intel", "Microsoft Basic"))]
    return (discrete or names or [None])[0]


@functools.lru_cache(maxsize=1)
def detect_gpu() -> str | None:
    """The main graphics card's name, or None when there's no dedicated one to report.
    Hardware doesn't change while the app runs, and probing spawns processes, so the
    answer is computed once."""
    nvidia = nvidia_gpu()
    if nvidia:
        return nvidia.name
    if sys.platform == "win32":
        return _windows_gpu()
    if sys.platform.startswith("linux"):
        return _linux_gpu()
    return None


def has_dedicated_gpu() -> bool:
    gpu = detect_gpu()
    return gpu is not None and not gpu.startswith(("Intel", "Microsoft Basic"))


def _os_name() -> str:
    return {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, platform.system() or "Linux")


def get_device_capabilities() -> DeviceCapabilities:
    vmem = psutil.virtual_memory()
    disk = psutil.disk_usage(str(get_data_dir()))
    return DeviceCapabilities(
        ram_total_gb=round(vmem.total / _BYTES_PER_GB, 2),
        ram_available_gb=round(vmem.available / _BYTES_PER_GB, 2),
        cpu_physical_cores=psutil.cpu_count(logical=False) or 1,
        cpu_logical_cores=psutil.cpu_count(logical=True) or 1,
        disk_free_gb=round(disk.free / _BYTES_PER_GB, 2),
        disk_total_gb=round(disk.total / _BYTES_PER_GB, 2),
        gpu_name=detect_gpu(),
        gpu_memory_gb=nvidia.memory_gb if (nvidia := nvidia_gpu()) else None,
        os_name=_os_name(),
        arch=platform.machine().lower() or "unknown",
    )
