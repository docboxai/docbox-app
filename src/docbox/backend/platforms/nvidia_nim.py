"""Discovers vision-language models available through NVIDIA's NIM API catalog
(integrate.api.nvidia.com), for users who've opted in with their own API key.

This is the one platform integration in DocBox that leaves the machine: images run
through an NVIDIA NIM model are sent to NVIDIA's cloud API. It's opt-in only — no model
from here appears in the catalog until the user enters an API key in the Platforms view
— and every model built from this module is labeled as a cloud call.

NVIDIA's hosted catalog is large and changes over time, so rather than hardcode a
model list this queries the catalog's own `GET /v1/models` listing (OpenAI-compatible,
like the rest of NIM's chat API) and filters by name for the vision/OCR-shaped ones.
"""

from __future__ import annotations

import re

import requests

from docbox.backend.core import config_store
from docbox.backend.core.registry import ModelSpec
from docbox.backend.engines.nvidia_nim_engine import NIM_BASE_URL, NvidiaNimOcrEngine

_VISION_KEYWORD_RE = re.compile(
    r"vision|-vl-|-vl$|vl-instruct|ocr|paligemma|vila|llava|kosmos|florence|multimodal",
    re.IGNORECASE,
)


def _is_vision_model(model_id: str) -> bool:
    return bool(_VISION_KEYWORD_RE.search(model_id))


def _fetch_models(timeout: float = 5.0) -> list[str] | None:
    api_key = config_store.get_nvidia_api_key()
    if not api_key:
        return None
    try:
        resp = requests.get(
            f"{NIM_BASE_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return None
    return [m["id"] for m in resp.json().get("data", []) if "id" in m]


def status() -> dict:
    api_key = config_store.get_nvidia_api_key()
    if not api_key:
        return {
            "id": "nvidia-nim",
            "name": "NVIDIA NIM",
            "available": False,
            "detail": "No API key configured. Get one at https://build.nvidia.com and "
            "add it here. Sends image data to NVIDIA's cloud — not local.",
        }
    models = _fetch_models()
    if models is None:
        return {
            "id": "nvidia-nim",
            "name": "NVIDIA NIM",
            "available": False,
            "detail": "API key set, but the catalog couldn't be reached — check the "
            "key and your network connection.",
        }
    vision_count = sum(1 for m in models if _is_vision_model(m))
    return {
        "id": "nvidia-nim",
        "name": "NVIDIA NIM",
        "available": True,
        "detail": f"{vision_count} vision-capable model(s) available. Cloud calls, "
        "billed to your NVIDIA account.",
    }


def _spec_for(nim_model: str) -> ModelSpec:
    return ModelSpec(
        id=f"nvidia-nim:{nim_model}",
        name=f"NVIDIA NIM — {nim_model}",
        engine="nvidia-nim",
        description=(
            "Cloud-hosted vision-language model called through NVIDIA's NIM API. "
            "Sends the image being processed to NVIDIA's servers — this is the only "
            "model type in DocBox that isn't local-only."
        ),
        languages=["multi"],
        approx_download_mb=0,
        approx_ram_mb=0,
        min_disk_mb=0,
        engine_factory=lambda m=nim_model: NvidiaNimOcrEngine(
            model_id=f"nvidia-nim:{m}", nim_model=m
        ),
    )


def list_models() -> list[ModelSpec]:
    models = _fetch_models()
    if not models:
        return []
    return [_spec_for(m) for m in models if _is_vision_model(m)]


def get_model_spec(model_id: str) -> ModelSpec | None:
    if config_store.get_nvidia_api_key() is None:
        return None
    nim_model = model_id.split(":", 1)[1] if ":" in model_id else ""
    if not nim_model:
        return None
    return _spec_for(nim_model)
