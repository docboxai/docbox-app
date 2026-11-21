"""PaddleOCR-VL downloads the models its pipeline reads with, and has the packages it needs."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from docbox.backend.core import runtime
from docbox.backend.core.paths import get_models_dir
from docbox.backend.engines import paddleocr_vl_engine
from docbox.backend.engines.paddleocr_vl_engine import PaddleOcrVlEngine

needs_paddle = pytest.mark.skipif(
    not runtime.extra_installed("paddle"),
    reason="needs the paddle extra (CI and `uv sync --extra paddle` have it)",
)


def _official_models_dir() -> Path:
    return get_models_dir() / "paddlex_cache" / "official_models"


@pytest.fixture
def fake_official_models(monkeypatch, data_dir) -> list[str]:
    """paddlex's `official_models[name]`, creating the folder instead of downloading."""
    fetched: list[str] = []

    class FakeModels:
        def __getitem__(self, name: str) -> Path:
            fetched.append(name)
            folder = _official_models_dir() / paddleocr_vl_engine._MODELS[name]
            folder.mkdir(parents=True, exist_ok=True)
            return folder

    module = types.ModuleType("paddlex.inference.utils.official_models")
    module.official_models = FakeModels()
    monkeypatch.setitem(sys.modules, "paddlex.inference.utils.official_models", module)
    monkeypatch.delenv("PADDLE_PDX_CACHE_HOME", raising=False)
    return fetched


def test_download_fetches_every_model_and_drops_the_old_reader(fake_official_models) -> None:
    """DocBox 0.1.1 downloaded the first PaddleOCR-VL (2 GB), which the pipeline never
    used: it fetched PP-DocLayoutV3 and PaddleOCR-VL-1.6 during the first read instead."""
    legacy = _official_models_dir() / "PaddleOCR-VL"
    legacy.mkdir(parents=True)
    engine = PaddleOcrVlEngine(model_id="paddleocr-vl")
    assert not engine.is_downloaded()  # the old download alone isn't enough

    engine.download(lambda _pct, _msg: None)

    assert fake_official_models == list(paddleocr_vl_engine._MODELS)
    assert engine.is_downloaded()
    assert not legacy.exists()


def test_delete_removes_every_model(fake_official_models) -> None:
    engine = PaddleOcrVlEngine(model_id="paddleocr-vl")
    engine.download(lambda _pct, _msg: None)
    (_official_models_dir() / "PaddleOCR-VL").mkdir()

    engine.delete()

    assert not engine.is_downloaded()
    assert not any(_official_models_dir().iterdir())


@needs_paddle
def test_models_are_the_ones_the_pinned_pipeline_uses() -> None:
    import paddlex
    import yaml

    version = paddleocr_vl_engine._PIPELINE_VERSION.removeprefix("v")
    config_path = (Path(paddlex.__file__).parent / "configs" / "pipelines"
                   / f"PaddleOCR-VL-{version}.yaml")
    sub = yaml.safe_load(config_path.read_text(encoding="utf-8"))["SubModules"]
    used = {sub["LayoutDetection"]["model_name"], sub["VLRecognition"]["model_name"]}
    assert used == set(paddleocr_vl_engine._MODELS)


@needs_paddle
def test_paddle_extra_has_what_the_vl_pipeline_needs() -> None:
    """Without paddlex's `ocr` extra the pipeline refuses to start ("A dependency error
    occurred during pipeline creation"), after the user downloaded 2 GB for it."""
    from paddlex.utils.deps import is_extra_available

    assert is_extra_available("ocr")


def test_dependency_closure_follows_extras() -> None:
    # The base install has uvicorn[standard]; its extra pulls in watchfiles.
    assert "watchfiles" not in runtime._dist_closure(("uvicorn",))
    assert "watchfiles" in runtime._dist_closure(("uvicorn[standard]",))
