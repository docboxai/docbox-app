from __future__ import annotations

from fastapi import APIRouter

from docbox.backend.api.errors import http_errors
from docbox.backend.schemas import Settings, SettingsUpdate
from docbox.service import settings as service

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=Settings)
def get_settings() -> Settings:
    return service.get_settings()


@router.patch("", response_model=Settings)
def update_settings(body: SettingsUpdate) -> Settings:
    with http_errors():
        return service.update_settings(body)
