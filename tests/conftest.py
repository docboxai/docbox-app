"""Fixtures shared by every test folder: settings and the data dir in a temp dir, and a
fake OCR model that reads instantly without any engine installed."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from docbox.backend.core import config_store
from docbox.backend.core.registry import ModelSpec, registry
from docbox.backend.schemas import OcrLine, OcrResult

FAKE_ID = "test-fake"


@pytest.fixture(autouse=True)
def _isolated_settings_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config_store, "_settings_path", lambda: tmp_path / "settings.json")


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "data"
    monkeypatch.setenv("DOCBOX_DATA_DIR", str(d))
    monkeypatch.setattr(config_store, "get_output_dir", lambda: tmp_path / "out")
    return d


class FakeEngine:
    """Reads every page as the same two lines; 'downloads' by writing a marker file."""

    text = "Total due $1,284.00\nRef INV-0312"

    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def is_downloaded(self) -> bool:
        return self.marker.exists()

    def download(self, progress_cb) -> None:
        progress_cb(50.0, "half")
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text("ok")
        progress_cb(100.0, "done")

    def load(self) -> None:
        pass

    def run(self, image: Image.Image) -> OcrResult:
        lines = [OcrLine(text=t, confidence=0.9) for t in self.text.split("\n")]
        return OcrResult(model_id=FAKE_ID, lines=lines, text=self.text)

    def delete(self) -> None:
        self.marker.unlink(missing_ok=True)


@pytest.fixture()
def fake_model(data_dir: Path):
    """A registered model `test-fake`, not yet installed."""
    marker = data_dir / "models" / "fake" / "weights"
    spec = ModelSpec(
        id=FAKE_ID, name="Fake OCR", engine="fake", description="test double",
        languages=["en"], approx_download_mb=1, approx_ram_mb=1, min_disk_mb=1,
        engine_factory=lambda: FakeEngine(marker),
    )
    registry.register(spec)
    yield spec
    registry._models.pop(FAKE_ID, None)


@pytest.fixture()
def installed_fake(fake_model):
    fake_model.engine_factory().download(lambda *_: None)
    return fake_model


@pytest.fixture()
def sample_image(tmp_path: Path) -> Path:
    path = tmp_path / "docs" / "invoice.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (200, 80), "white").save(path)
    return path
