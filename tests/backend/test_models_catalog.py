from __future__ import annotations

import sys

import pytest

from docbox.backend.core.registry import registry
from docbox.backend.engines.easyocr_engine import EasyOcrEngine
from docbox.backend.engines.tesseract_engine import TesseractEngine


def test_catalog_covers_multiple_engines_and_language_families() -> None:
    specs = {s.id: s for s in registry.list()}

    expected_ids = {
        "paddleocr-mobile-en",
        "paddleocr-mobile-ch",
        "paddleocr-balanced",
        "paddleocr-accurate-en",
        "paddleocr-latin",
        "paddleocr-cyrillic",
        "paddleocr-arabic",
        "paddleocr-devanagari",
        "paddleocr-korean",
        "paddleocr-vl",
        "tesseract-eng",
        "tesseract-fra",
        "easyocr-en",
    }
    assert expected_ids <= specs.keys()

    engines = {s.engine for s in specs.values()}
    assert {"paddleocr", "paddleocr-vl", "tesseract", "easyocr"} <= engines


def test_language_family_specs_are_distinct_not_all_the_same() -> None:
    # Regression guard for the classic late-binding closure bug: each entry built in a
    # loop must keep its own det/rec model names and languages, not all collapse to the
    # last iteration's values.
    latin = registry.get("paddleocr-latin")
    korean = registry.get("paddleocr-korean")

    assert latin.languages != korean.languages
    assert latin.engine_factory()._rec_model_name != korean.engine_factory()._rec_model_name


def test_tesseract_engine_reports_missing_binary_clearly() -> None:
    from docbox.backend.engines.tesseract_engine import find_tesseract_binary

    if find_tesseract_binary() is not None:
        pytest.skip("the tesseract program is installed in this environment")

    spec = registry.get("tesseract-eng")
    engine: TesseractEngine = spec.engine_factory()

    assert engine.is_downloaded() is False

    with pytest.raises(RuntimeError) as excinfo:
        engine.download(lambda pct, msg: None)

    message = str(excinfo.value).lower()
    assert "tesseract" in message
    assert "install" in message


def test_easyocr_engine_reports_not_downloaded_when_package_absent() -> None:
    spec = registry.get("easyocr-en")
    engine: EasyOcrEngine = spec.engine_factory()

    if "easyocr" in sys.modules:
        pytest.skip("easyocr is already importable in this environment")

    assert engine.is_downloaded() is False
