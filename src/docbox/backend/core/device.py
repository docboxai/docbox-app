"""Device hardware-capability detection (RAM / CPU / disk)."""

from __future__ import annotations

import psutil

from docbox.backend.core.paths import get_data_dir
from docbox.backend.schemas import DeviceCapabilities

_BYTES_PER_GB = 1024**3


def get_device_capabilities() -> DeviceCapabilities:
    vmem = psutil.virtual_memory()
    disk = psutil.disk_usage(str(get_data_dir()))
    return DeviceCapabilities(
        ram_total_gb=round(vmem.total / _BYTES_PER_GB, 2),
        ram_available_gb=round(vmem.available / _BYTES_PER_GB, 2),
        cpu_physical_cores=psutil.cpu_count(logical=False) or 1,
        cpu_logical_cores=psutil.cpu_count(logical=True) or 1,
        disk_free_gb=round(disk.free / _BYTES_PER_GB, 2),
    )
