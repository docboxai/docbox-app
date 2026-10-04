from __future__ import annotations

from fastapi import APIRouter, HTTPException

from docbox.backend import platforms
from docbox.backend.core import config_store
from docbox.backend.schemas import Settings, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _current() -> Settings:
    return Settings(
        default_model_id=config_store.get_default_model_id(),
        cloud_enabled=config_store.cloud_enabled(),
        output_dir=str(config_store.get_output_dir()),
    )


@router.get("", response_model=Settings)
def get_settings() -> Settings:
    return _current()


@router.patch("", response_model=Settings)
def update_settings(body: SettingsUpdate) -> Settings:
    if body.cloud_enabled is not None:
        config_store.set_cloud_enabled(body.cloud_enabled)
    if body.default_model_id is not None:
        if body.default_model_id:
            try:
                platforms.resolve_spec(body.default_model_id)
            except KeyError:
                raise HTTPException(
                    status_code=404, detail=f"Unknown model: {body.default_model_id}"
                ) from None
        config_store.set_default_model_id(body.default_model_id or None)
    return _current()
