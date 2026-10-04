"""External platforms DocBox can discover OCR-capable models through, beyond its own
static catalog (`docbox.backend.models_catalog`). Unlike the static catalog, these
models aren't registered once at import time — what's available can change any time
(the user pulls/removes an Ollama model, adds/removes an NVIDIA API key), so they're
(re)discovered fresh on every request instead of cached in the `ModelRegistry` singleton.
"""

from __future__ import annotations

from docbox.backend.core import config_store
from docbox.backend.core.registry import ModelSpec, registry
from docbox.backend.platforms import nvidia_nim, ollama


def list_platform_statuses() -> list[dict]:
    return [ollama.status(), nvidia_nim.status()]


def list_dynamic_specs() -> list[ModelSpec]:
    """All models discoverable through external platforms right now.

    Each platform's own lookup swallows its errors (server not running, bad API key,
    network failure) and returns an empty list rather than raising — one platform being
    unreachable shouldn't break the rest of the model catalog.
    """
    return [*ollama.list_models(), *nvidia_nim.list_models()]


def resolve_spec(model_id: str) -> ModelSpec:
    """Look up a model id across the static registry and every dynamic platform."""
    try:
        return registry.get(model_id)
    except KeyError:
        pass

    if model_id.startswith("ollama:"):
        spec = ollama.get_model_spec(model_id)
    elif model_id.startswith("nvidia-nim:"):
        spec = nvidia_nim.get_model_spec(model_id)
    else:
        spec = None

    if spec is None:
        raise KeyError(f"Unknown model id: {model_id}")
    return spec


def cloud_blocked(model_id: str) -> bool:
    """True for a cloud model while the user has the cloud engine switched off."""
    return model_id.startswith("nvidia-nim:") and not config_store.cloud_enabled()
