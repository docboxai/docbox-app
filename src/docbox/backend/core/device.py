"""Device hardware-capability detection (RAM / CPU / disk / graphics)."""

from __future__ import annotations

import functools
import platform
import shutil
import subprocess
import sys

import psutil

from docbox.backend.core.paths import get_data_dir
from docbox.backend.schemas import DeviceCapabilities

_BYTES_PER_GB = 1024**3
_PROBE_TIMEOUT_S = 4.0


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


def _nvidia_gpu() -> str | None:
    if not shutil.which("nvidia-smi"):
        return None
    out = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    names = [line.strip() for line in (out or "").splitlines() if line.strip()]
    return names[0] if names else None


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
    gpu = _nvidia_gpu()
    if gpu:
        return gpu
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
        os_name=_os_name(),
        arch=platform.machine().lower() or "unknown",
    )
