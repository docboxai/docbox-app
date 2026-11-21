"""Reading big images in strips, the RAM limit (fit, recommendation, refusing a read) and
where each model reads best (issue #23)."""

from __future__ import annotations

import io
import itertools
import sys
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from docbox.backend import models_catalog
from docbox.backend.core import config_store, device, engine_cache, reader
from docbox.backend.core.paths import get_models_dir
from docbox.backend.core.registry import (
    ModelSpec,
    check_fit,
    inference_device,
    recommend,
    registry,
)
from docbox.backend.engines import paddleocr_engine
from docbox.backend.engines.paddleocr_engine import PaddleOcrEngine, _strips
from docbox.backend.schemas import DeviceCapabilities, OcrLine, OcrResult


def _caps(**overrides) -> DeviceCapabilities:
    base = {
        "ram_total_gb": 16, "ram_available_gb": 8, "cpu_physical_cores": 8,
        "cpu_logical_cores": 16, "disk_free_gb": 100, "disk_total_gb": 500, "gpu_name": None,
        "os_name": "Linux", "arch": "x86_64",
    }
    return DeviceCapabilities(**{**base, **overrides})


def _spec(**overrides) -> ModelSpec:
    base = {
        "id": "t", "name": "T", "engine": "fake", "description": "", "languages": ["en"],
        "approx_download_mb": 1, "approx_ram_mb": 100, "min_disk_mb": 1,
        "engine_factory": lambda: None,
    }
    return ModelSpec(**{**base, **overrides})


# --- strips ----------------------------------------------------------------------------


def test_pages_are_read_whole_and_tall_screenshots_in_strips() -> None:
    assert _strips(1654, 2339) == [(0, 0, 1654, 2339)]  # A4 at 200 dpi

    strips = _strips(1920, 13768)  # the screenshot from issue #23
    assert len(strips) > 1
    assert strips[0][1] == 0 and strips[-1][3] == 13768
    for (_, top, right, bottom), (_, next_top, _, _) in itertools.pairwise(strips):
        assert right == 1920
        assert bottom - next_top == paddleocr_engine._OVERLAP
    for left, top, right, bottom in strips:
        # Never shrunk by paddle, and never more than a page's worth of pixels at once.
        assert bottom - top <= paddleocr_engine._MAX_SIDE
        assert (right - left) * (bottom - top) <= paddleocr_engine._STRIP_PIXELS

    wide = _strips(13768, 1000)
    assert all(top == 0 and bottom == 1000 for _, top, _, bottom in wide)
    assert wide[-1][2] == 13768


def _striped_image(width: int, height: int) -> Image.Image:
    """Each row's red and green say its y, so a fake engine can tell where a crop came from."""
    image = Image.new("RGB", (width, height))
    for y in range(height):
        image.paste((y % 256, y // 256, 0), (0, y, width, y + 1))
    return image


_LINE_EVERY = 90
_LINE_HEIGHT = 30


def _fake_run_one(image: Image.Image) -> list[OcrLine]:
    """One line of text every 90 px of the full image, reported where it lies in the crop
    and only when it lies wholly inside it, like a real text finder."""
    red, green, _ = image.getpixel((0, 0))
    top = green * 256 + red
    lines = []
    for y in range(0, top + image.height, _LINE_EVERY):
        if y >= top and y + _LINE_HEIGHT <= top + image.height:
            lines.append(OcrLine(text=f"line {y}", box=[10, y - top, 200, y - top + _LINE_HEIGHT]))
    return lines


def test_strips_read_every_line_once_in_place(monkeypatch) -> None:
    monkeypatch.setattr(paddleocr_engine, "_STRIP_PIXELS", 40 * 1000)  # 1000 px strips
    engine = PaddleOcrEngine(model_id="m", det_model_name="d", rec_model_name="r")
    engine._ocr = object()
    monkeypatch.setattr(engine, "_run_one", _fake_run_one)

    result = engine.run(_striped_image(40, 5000))

    expected = [y for y in range(0, 5000, _LINE_EVERY) if y + _LINE_HEIGHT <= 5000]
    assert [line.text for line in result.lines] == [f"line {y}" for y in expected]
    assert [line.box[1] for line in result.lines] == expected


def test_a_line_on_the_cut_is_kept_once(monkeypatch) -> None:
    """Strips meet at y=900 here. Each reports a line centred on the cut a pixel apart, so
    by its centre each strip owns its own copy."""
    monkeypatch.setattr(paddleocr_engine, "_STRIP_PIXELS", 40 * 1000)
    engine = PaddleOcrEngine(model_id="m", det_model_name="d", rec_model_name="r")
    engine._ocr = object()

    def run_one(image: Image.Image) -> list[OcrLine]:
        red, green, _ = image.getpixel((0, 0))
        top = green * 256 + red
        if top == 0:
            return [OcrLine(text="on the cut", box=[10, 885, 200, 914])]
        if top == 800:
            return [OcrLine(text="on the cut", box=[10, 86, 200, 115])]
        return []

    monkeypatch.setattr(engine, "_run_one", run_one)
    result = engine.run(_striped_image(40, 2500))
    assert [line.text for line in result.lines] == ["on the cut"]


# --- the RAM limit -----------------------------------------------------------------------


def test_models_over_the_ram_limit_dont_fit_and_arent_recommended() -> None:
    big = _spec(id="big", approx_ram_mb=2700, quality=50)
    small = _spec(id="small", approx_ram_mb=1000, quality=30)
    caps = _caps()

    assert check_fit(big, caps).fits
    fit = check_fit(big, caps, ram_limit_gb=2)
    assert not fit.fits and fit.summary == "Over your RAM limit"
    assert fit.reasons == ["Takes about 2.6 GB while reading, over your 2 GB limit"]

    assert recommend([big, small], caps) is big
    assert recommend([big, small], caps, ram_limit_gb=2) is small


def test_ram_limit_setting_roundtrip(client: TestClient) -> None:
    assert client.get("/api/settings").json()["ram_limit_gb"] is None
    assert client.patch("/api/settings", json={"ram_limit_gb": 4.25}).json()["ram_limit_gb"] == 4.2
    assert client.patch("/api/settings", json={"ram_limit_gb": -1}).status_code == 400
    assert client.patch("/api/settings", json={"ram_limit_gb": 0}).json()["ram_limit_gb"] is None

    client.patch("/api/settings", json={"ram_limit_gb": 2})
    models = {m["id"]: m for m in client.get("/api/models").json()}
    assert models["paddleocr-accurate-en"]["fit"]["summary"] == "Over your RAM limit"
    assert models["paddleocr-mobile-en"]["fit"]["summary"] != "Over your RAM limit"


class _Engine:
    def is_downloaded(self) -> bool:
        return True

    def download(self, progress_cb) -> None:
        pass

    def load(self) -> None:
        pass

    def run(self, image):
        return OcrResult(model_id="test-heavy", lines=[OcrLine(text="hi")], text="hi")

    def delete(self) -> None:
        pass


@pytest.fixture()
def heavy_spec():
    spec = _spec(id="test-heavy", name="Heavy", approx_ram_mb=4096, engine_factory=_Engine)
    registry.register(spec)
    yield spec
    registry._models.pop(spec.id, None)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buf, format="PNG")
    return buf.getvalue()


def _read(client: TestClient) -> dict:
    resp = client.post(
        "/api/reads",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={"model_id": "test-heavy", "output_format": "txt"},
    )
    read_id = resp.json()["reads"][0]["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body = client.get(f"/api/reads/{read_id}").json()
        if body["state"] in ("done", "error", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"read never finished: {body}")


def test_read_is_refused_over_the_ram_limit(client: TestClient, heavy_spec) -> None:
    client.patch("/api/settings", json={"ram_limit_gb": 3})
    body = _read(client)
    assert body["state"] == "error"
    assert "takes about 4 GB of memory to read a page, over your 3 GB limit" in body["error"]


def test_read_is_refused_when_the_memory_isnt_free(
    client: TestClient, heavy_spec, monkeypatch
) -> None:
    monkeypatch.setattr(
        reader.psutil, "virtual_memory", lambda: SimpleNamespace(available=1 * 2**30)
    )
    body = _read(client)
    assert body["state"] == "error"
    assert "only 1 GB is free" in body["error"]


def test_one_page_ocr_is_refused_over_the_ram_limit(client: TestClient, heavy_spec) -> None:
    client.patch("/api/settings", json={"ram_limit_gb": 3})
    resp = client.post(
        "/api/ocr/run",
        files={"file": ("a.png", _png(), "image/png")},
        data={"model_id": "test-heavy", "page": "0"},
    )
    assert resp.status_code == 409
    assert "over your 3 GB limit" in resp.json()["detail"]


def test_models_running_elsewhere_are_never_refused_for_memory(monkeypatch) -> None:
    class _Elsewhere(_Engine):
        runs_in_process = False  # Ollama, the cloud, an engine container

    spec = _spec(id="test-elsewhere", approx_ram_mb=64_000, engine_factory=_Elsewhere)
    config_store.set_ram_limit_gb(1)
    monkeypatch.setattr(
        reader.psutil, "virtual_memory", lambda: SimpleNamespace(available=0)
    )
    reader.check_memory(spec)  # doesn't raise


def test_a_loaded_model_skips_the_free_memory_check(heavy_spec, monkeypatch) -> None:
    # Its memory is already taken, so what's free now doesn't matter; the limit still does.
    monkeypatch.setattr(
        reader.psutil, "virtual_memory", lambda: SimpleNamespace(available=1 * 2**30)
    )
    monkeypatch.setattr(engine_cache, "loaded_model_ids", lambda: ["test-heavy"])
    reader.check_memory(heavy_spec)

    config_store.set_ram_limit_gb(3)
    with pytest.raises(reader.NotRunnable, match="over your 3 GB limit"):
        reader.check_memory(heavy_spec)


# --- what keeps paddle's memory down ------------------------------------------------------


def test_paddle_pipelines_are_built_with_onednn(monkeypatch) -> None:
    """Without oneDNN paddle takes about 5 GB per megapixel (issue #23)."""
    built: dict = {}
    fake = SimpleNamespace(PaddleOCR=lambda **kwargs: built.update(kwargs))
    monkeypatch.setitem(sys.modules, "paddleocr", fake)
    monkeypatch.setenv("PADDLE_PDX_CACHE_HOME", str(get_models_dir() / "paddlex_cache"))

    PaddleOcrEngine(model_id="m", det_model_name="d", rec_model_name="r")._build_pipeline()
    assert built["enable_mkldnn"] is True


def test_paddle_stays_below_3_3_which_breaks_onednn() -> None:
    root = Path(__file__).resolve().parents[2]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    assert "paddlepaddle>=3.2,<3.3" in pyproject["project"]["optional-dependencies"]["paddle"]
    lock = tomllib.loads((root / "uv.lock").read_text())
    versions = {p["version"] for p in lock["package"] if p["name"] == "paddlepaddle"}
    assert versions and all(v.startswith("3.2.") for v in versions), versions


# --- where models read best --------------------------------------------------------------


def test_nvidia_cards_report_their_memory(monkeypatch) -> None:
    device._nvidia_gpu.cache_clear()
    monkeypatch.setattr(device.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(device, "_run", lambda cmd: "NVIDIA GeForce RTX 3060, 12288\n")
    try:
        assert device._nvidia_gpu() == ("NVIDIA GeForce RTX 3060", 12.0)
        monkeypatch.setattr(device, "_run", lambda cmd: "garbage\n")
        device._nvidia_gpu.cache_clear()
        assert device._nvidia_gpu() is None
    finally:
        device._nvidia_gpu.cache_clear()


def test_models_api_carries_figures_and_device(client: TestClient) -> None:
    models = {m["id"]: m for m in client.get("/api/models").json()}
    large = models["paddleocr-accurate-en"]
    assert large["ram_measured"] is True
    assert large["approx_ram_mb"] == 3200
    assert large["cpu_page_seconds"] == 5.1
    assert large["figures_source"] == models_catalog._PADDLE_FIGURES
    assert (large["device"]["runs_on"], large["device"]["preferred"]) == ("cpu", "gpu")

    mobile = models["paddleocr-mobile-en"]
    assert mobile["device"]["preferred"] == "cpu" and mobile["device"]["note"] is None


def test_gpu_models_say_how_much_faster_a_graphics_card_would_be() -> None:
    large = _spec(preferred_device="gpu", gpu_speedup=4.3)
    rtx = _caps(gpu_name="NVIDIA GeForce RTX 3060", gpu_memory_gb=12.0)

    device = inference_device(large, rtx)
    assert (device.runs_on, device.preferred) == ("cpu", "gpu")
    assert "about 4.3× faster" in device.note and "RTX 3060" in device.note

    assert inference_device(_spec(), rtx).note is None  # quick on the processor anyway

    ollama = _spec(preferred_device="gpu", runs_on_gpu=True)
    assert inference_device(ollama, rtx).runs_on == "gpu"
    assert inference_device(ollama, rtx).note is None
    assert "lacks" in inference_device(ollama, _caps()).note


def test_catalog_figures_name_their_source() -> None:
    for spec in registry.list():
        if spec.ram_measured or spec.gpu_speedup:
            assert spec.figures_source, spec.id
        if spec.engine == "tesseract":
            assert spec.preferred_device == "cpu"
