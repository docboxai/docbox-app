"""The default model, the cloud-engine switch, the RAM limit and the output folder."""

from __future__ import annotations

import docbox.backend.models_catalog  # noqa: F401 — importing it fills the registry
from docbox.backend import platforms
from docbox.backend.core import config_store
from docbox.backend.schemas import Settings, SettingsUpdate
from docbox.service.errors import Invalid, NotFound


def get_settings() -> Settings:
    return Settings(
        default_model_id=config_store.get_default_model_id(),
        cloud_enabled=config_store.cloud_enabled(),
        output_dir=str(config_store.get_output_dir()),
        ram_limit_gb=config_store.get_ram_limit_gb(),
    )


def update_settings(update: SettingsUpdate) -> Settings:
    if update.cloud_enabled is not None:
        config_store.set_cloud_enabled(update.cloud_enabled)
    if update.default_model_id is not None:
        if update.default_model_id:
            try:
                platforms.resolve_spec(update.default_model_id)
            except KeyError:
                raise NotFound(f"Unknown model: {update.default_model_id}") from None
        config_store.set_default_model_id(update.default_model_id or None)
    if update.ram_limit_gb is not None:
        if update.ram_limit_gb < 0:
            raise Invalid("The RAM limit can't be negative")
        config_store.set_ram_limit_gb(round(update.ram_limit_gb, 1) or None)
    return get_settings()
