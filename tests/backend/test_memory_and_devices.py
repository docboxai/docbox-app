"""Reading big images in strips, the RAM limit (fit, recommendation, refusing a read) and
where each model reads best (issue #23)."""

from __future__ import annotations

import io
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from docbox.backend.core import reader
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
    for (_, top, right, bottom), (_, next_top, _, _) in zip(strips, strips[1:]):
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


# --- where models read best --------------------------------------------------------------


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
