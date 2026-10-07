"""Setup's recommendation: the best-reading built-in model that runs smoothly here."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import docbox.backend.models_catalog  # noqa: F401 — registers the built-in models
from docbox.backend.core.registry import ModelSpec, Tier, recommend, registry, runs_smoothly
from docbox.backend.schemas import DeviceCapabilities
from docbox.service import models as service_models


def _caps(**overrides) -> DeviceCapabilities:
    base = {
        "ram_total_gb": 16, "ram_available_gb": 8, "cpu_physical_cores": 8,
        "cpu_logical_cores": 16, "disk_free_gb": 100, "disk_total_gb": 500, "gpu_name": None,
        "os_name": "Linux", "arch": "x86_64",
    }
    return DeviceCapabilities(**{**base, **overrides})


def _spec(id: str, **overrides) -> ModelSpec:
    base = {
        "id": id, "name": id, "engine": "fake", "description": "", "languages": ["en"],
        "approx_download_mb": 1, "approx_ram_mb": 100, "min_disk_mb": 1,
        "engine_factory": lambda: None, "quality": 10,
    }
    return ModelSpec(**{**base, **overrides})


def _pick(specs: list[ModelSpec], **caps) -> str | None:
    best = recommend(specs, _caps(**caps))
    return best.id if best else None


# --- the rule -----------------------------------------------------------------------


def test_best_quality_wins_not_the_heaviest_tier() -> None:
    # A heavier model is only worth recommending when it also reads better.
    light_good = _spec("light-good", tier=Tier.LIGHT, quality=60)
    standard_worse = _spec("standard-worse", tier=Tier.STANDARD, quality=50)
    assert _pick([standard_worse, light_good]) == "light-good"


def test_tier_gates_on_total_ram_and_cores() -> None:
    small = _spec("small", tier=Tier.LIGHT, quality=10)
    standard = _spec("standard", tier=Tier.STANDARD, quality=50)
    heavy = _spec("heavy", tier=Tier.HEAVY, quality=90)
    specs = [small, standard, heavy]
    assert _pick(specs, ram_total_gb=16, cpu_physical_cores=8) == "heavy"
    assert _pick(specs, ram_total_gb=16, cpu_physical_cores=6) == "standard"
    # An "8 GB" laptop reports a little under 8 once the graphics take their share.
    assert _pick(specs, ram_total_gb=7.6, cpu_physical_cores=4) == "standard"
    assert _pick(specs, ram_total_gb=7.6, cpu_physical_cores=2) == "small"
    assert _pick(specs, ram_total_gb=4, cpu_physical_cores=4) == "small"


def test_slow_without_a_gpu_is_never_recommended() -> None:
    cpu_vlm = _spec("cpu-vlm", tier=Tier.LIGHT, quality=90, slow_on_cpu=True)
    fallback = _spec("fallback", quality=10)
    # Built-in engines run on the CPU, so a graphics card doesn't make them fast.
    assert _pick([cpu_vlm, fallback], gpu_name="NVIDIA GeForce RTX 4090") == "fallback"

    gpu_vlm = _spec("gpu-vlm", quality=90, slow_on_cpu=True, runs_on_gpu=True)
    assert _pick([gpu_vlm, fallback], gpu_name="NVIDIA GeForce RTX 4090") == "gpu-vlm"
    assert _pick([gpu_vlm, fallback], gpu_name="Intel UHD Graphics 630") == "fallback"


def test_must_fit_free_memory_and_disk_now() -> None:
    big = _spec("big", quality=90, approx_ram_mb=6000, min_disk_mb=4000)
    small = _spec("small", quality=10)
    assert _pick([big, small]) == "big"
    assert _pick([big, small], ram_available_gb=4) == "small"
    assert _pick([big, small], disk_free_gb=2) == "small"
    assert not runs_smoothly(big, _caps(ram_available_gb=4))


def test_unranked_models_are_never_picked() -> None:
    specialist = _spec("specialist", quality=None)
    assert _pick([specialist]) is None
    assert _pick([]) is None


def test_ties_keep_the_first_listed() -> None:
    assert _pick([_spec("a", quality=50), _spec("b", quality=50)]) == "a"


# --- the real catalog ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("caps", "expected"),
    [
        # A typical 16 GB laptop or desktop, with or without a graphics card: PaddleOCR-VL
        # runs on the CPU either way, so it's slow and not recommended.
        ({}, "paddleocr-balanced"),
        ({"gpu_name": "NVIDIA GeForce RTX 4070"}, "paddleocr-balanced"),
        ({"ram_total_gb": 7.6, "ram_available_gb": 4, "cpu_physical_cores": 4}, "paddleocr-balanced"),
        # A small 4 GB, 2-core machine gets the light tier's best.
        ({"ram_total_gb": 4, "ram_available_gb": 2, "cpu_physical_cores": 2}, "paddleocr-mobile-en"),
        # Almost no disk left: only Tesseract's 50 MB fits.
        ({"disk_free_gb": 0.1}, "tesseract-eng"),
    ],
)
def test_catalog_pick_per_machine(caps: dict, expected: str) -> None:
    assert _pick(registry.list(), **caps) == expected


def test_catalog_never_recommends_a_language_specialist() -> None:
    for spec in registry.list():
        if spec.id.startswith(("paddleocr-latin", "paddleocr-cyrillic", "paddleocr-arabic",
                               "paddleocr-devanagari", "paddleocr-korean", "tesseract-fra")):
            assert spec.quality is None, spec.id


# --- the API ------------------------------------------------------------------------


def test_listing_flags_exactly_one_recommended_model(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(service_models, "get_device_capabilities", lambda: _caps())
    body = client.get("/api/models").json()
    assert [m["id"] for m in body if m["recommended"]] == ["paddleocr-balanced"]
    assert client.get("/api/models/paddleocr-balanced").json()["recommended"] is True
    assert client.get("/api/models/paddleocr-mobile-en").json()["recommended"] is False
