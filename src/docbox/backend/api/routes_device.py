from __future__ import annotations

from fastapi import APIRouter

from docbox.backend.core.device import get_device_capabilities
from docbox.backend.schemas import DeviceCapabilities

router = APIRouter(prefix="/api/device", tags=["device"])


@router.get("/capabilities", response_model=DeviceCapabilities)
def read_capabilities() -> DeviceCapabilities:
    return get_device_capabilities()
