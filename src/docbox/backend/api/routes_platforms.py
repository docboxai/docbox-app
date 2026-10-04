from __future__ import annotations

from fastapi import APIRouter, HTTPException

from docbox.backend.core import config_store
from docbox.backend.platforms import list_platform_statuses
from docbox.backend.schemas import NvidiaApiKeyRequest, NvidiaApiKeyStatus, PlatformStatus

router = APIRouter(prefix="/api/platforms", tags=["platforms"])


@router.get("", response_model=list[PlatformStatus])
def list_platforms() -> list[PlatformStatus]:
    return [PlatformStatus(**s) for s in list_platform_statuses()]


@router.get("/nvidia-nim/api-key", response_model=NvidiaApiKeyStatus)
def nvidia_api_key_status() -> NvidiaApiKeyStatus:
    # Whether a key is saved; the key itself never goes back to the client.
    return NvidiaApiKeyStatus(configured=config_store.get_nvidia_api_key() is not None)


@router.post("/nvidia-nim/api-key", response_model=NvidiaApiKeyStatus)
def set_nvidia_api_key(body: NvidiaApiKeyRequest) -> NvidiaApiKeyStatus:
    key = body.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")
    config_store.set_nvidia_api_key(key)
    return NvidiaApiKeyStatus(configured=True)


@router.delete("/nvidia-nim/api-key", response_model=NvidiaApiKeyStatus)
def clear_nvidia_api_key() -> NvidiaApiKeyStatus:
    config_store.clear_nvidia_api_key()
    return NvidiaApiKeyStatus(configured=False)
