"""This computer, as DocBox sees it when judging which models fit."""

from __future__ import annotations

from pydantic import BaseModel

from docbox import __version__
from docbox.backend.core.device import get_device_capabilities
from docbox.backend.core.paths import get_data_dir
from docbox.backend.schemas import DeviceCapabilities


class DeviceReport(BaseModel):
    version: str
    data_dir: str
    device: DeviceCapabilities


def device_info() -> DeviceReport:
    return DeviceReport(
        version=__version__, data_dir=str(get_data_dir()), device=get_device_capabilities()
    )
