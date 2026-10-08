"""Ollama as a model source: vision models already pulled, plus a short recommended list.

Ollama itself is a prerequisite (`core/prerequisites.py` offers a guided/one-click
install). Once it's running, any recommended model that isn't pulled yet is listed as
"not downloaded", and picking it pulls it through Ollama's own API with progress
(`engines/ollama_engine.py`). When Ollama isn't running, the recommended models are still
listed (marked as needing Ollama), so users can see what they'd get before installing it.
"""

from __future__ import annotations

from docbox.backend.core.registry import ModelSpec
from docbox.backend.engines.ollama_engine import (
    OllamaOcrEngine,
    fetch_tags,
    normalize_model_name,
)

# Ollama has no "is this a vision model" flag in /api/tags, so this matches on known
# vision-capable model family name prefixes (the part before the ":tag"). Not
# exhaustive — new vision models land in Ollama's library regularly — but covers the
# common ones as of late 2025/2026.
_VISION_FAMILY_PREFIXES = (
    "llava",
    "llama3.2-vision",
    "llama3.1-vision",
    "bakllava",
    "minicpm-v",
    "moondream",
    "qwen2-vl",
    "qwen2.5vl",
    "qwen2.5-vl",
    "qwen3-vl",
    "granite3.2-vision",
    "llava-llama3",
    "llava-phi3",
    "cogvlm",
    "pixtral",
)

# (ollama tag, download size in MB, blurb). Tags and sizes checked against
# ollama.com/library on 2026-10-03; ordered small to large.
RECOMMENDED_VISION_MODELS: tuple[tuple[str, int, str], ...] = (
    ("granite3.2-vision:2b", 2400,
     "IBM's small vision model built for document understanding: tables, charts, forms."),
    ("qwen2.5vl:3b", 3200, "Compact Qwen vision model with solid multilingual text reading."),
    ("minicpm-v:8b", 5500, "Strong OCR for its size; handles any aspect ratio up to ~1.8 MP."),
    ("qwen2.5vl:7b", 6000, "Larger Qwen vision model: more accurate on dense or messy pages."),
    ("llama3.2-vision:11b", 7800, "Meta's general vision model; capable but the heaviest here."),
)


def _is_vision_model(name: str) -> bool:
    family = name.split(":", 1)[0].lower()
    return any(family.startswith(p) for p in _VISION_FAMILY_PREFIXES)


def _fetch_tags(*, fresh: bool = False) -> list[dict] | None:
    return fetch_tags(fresh=fresh)


def is_running(*, fresh: bool = False) -> bool:
    return _fetch_tags(fresh=fresh) is not None


def status() -> dict:
    models = _fetch_tags()
    if models is None:
        return {
            "id": "ollama",
            "name": "Ollama",
            "available": False,
            "detail": "Ollama isn't running on this computer.",
        }
    vision_count = sum(1 for m in models if _is_vision_model(m.get("name", "")))
    return {
        "id": "ollama",
        "name": "Ollama",
        "available": True,
        "detail": f"{vision_count} vision-capable model(s) pulled" if vision_count
        else "Running. Pick a recommended vision model in Setup to pull it.",
    }


def family_and_variant(name: str) -> tuple[str, str | None]:
    """The tags of one Ollama model are its sizes and quantizations: "qwen2.5vl:7b" is
    the 7b variant of "Ollama — qwen2.5vl". "latest" names no size, so no variant."""
    base, _, tag = normalize_model_name(name).partition(":")
    return f"Ollama — {base}", (None if tag == "latest" else tag)


def _spec_for(name: str, size_mb: int, description: str | None = None) -> ModelSpec:
    size_mb = max(1, size_mb)
    family, variant = family_and_variant(name)
    return ModelSpec(
        id=f"ollama:{name}",
        name=f"Ollama — {name}",
        family=family,
        variant=variant,
        engine="ollama",
        description=description or (
            "Vision-language model in your local Ollama install. Runs entirely on your "
            "machine through Ollama."
        ),
        languages=["multi"],
        approx_download_mb=size_mb,
        approx_ram_mb=round(size_mb * 1.2),
        min_disk_mb=size_mb,
        engine_factory=lambda n=name: OllamaOcrEngine(model_id=f"ollama:{n}", ollama_model=n),
        prerequisite="ollama",
        # Vision-language models are slow on a CPU; Ollama uses a graphics card itself.
        slow_on_cpu=True,
        runs_on_gpu=True,
    )


def list_models() -> list[ModelSpec]:
    pulled = _fetch_tags() or []
    specs: list[ModelSpec] = []
    seen: set[str] = set()
    for m in pulled:
        name = m.get("name", "")
        if not _is_vision_model(name):
            continue
        seen.add(normalize_model_name(name))
        specs.append(_spec_for(name, round(m.get("size", 0) / 1_000_000)))
    for name, size_mb, blurb in RECOMMENDED_VISION_MODELS:
        if normalize_model_name(name) not in seen:
            specs.append(_spec_for(name, size_mb, blurb))
    return specs


def get_model_spec(model_id: str) -> ModelSpec | None:
    name = model_id.split(":", 1)[1] if ":" in model_id else ""
    if not name:
        return None
    for m in _fetch_tags() or []:
        if normalize_model_name(m.get("name", "")) == normalize_model_name(name):
            return _spec_for(m["name"], round(m.get("size", 0) / 1_000_000))
    for rec_name, size_mb, blurb in RECOMMENDED_VISION_MODELS:
        if normalize_model_name(rec_name) == normalize_model_name(name):
            return _spec_for(rec_name, size_mb, blurb)
    return None
