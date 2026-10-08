"""Settings, fit summaries, pausable downloads, whole-file reads and their history."""

from __future__ import annotations

import io
import json
import threading
import time
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from docbox.backend.core import config_store, reader
from docbox.backend.core.pages import count_pages, iter_pages
from docbox.backend.core.registry import ModelSpec, check_fit, registry
from docbox.backend.schemas import DeviceCapabilities, OcrLine, OcrResult, ReadPage


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("DOCBOX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config_store, "get_output_dir", lambda: tmp_path / "out")
    return tmp_path


def _caps(**overrides) -> DeviceCapabilities:
    base = {
        "ram_total_gb": 16, "ram_available_gb": 8, "cpu_physical_cores": 4,
        "cpu_logical_cores": 8, "disk_free_gb": 100, "disk_total_gb": 500, "gpu_name": None,
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


# --- fit summaries ------------------------------------------------------------------


def test_fit_summary_runs_well_and_ram_shortfall() -> None:
    assert check_fit(_spec(), _caps()).summary == "Runs well"
    fit = check_fit(_spec(approx_ram_mb=7600), _caps(ram_available_gb=4))
    assert not fit.fits
    assert fit.summary == "Needs 8 GB free RAM"  # 7600 + 512 MB margin, rounded up


def test_fit_notes_slow_vision_models_unless_their_engine_uses_the_gpu() -> None:
    vl = _spec(slow_on_cpu=True)
    assert check_fit(vl, _caps(gpu_name="NVIDIA GeForce RTX 4070")).summary == "Slow without a GPU"

    ollama = _spec(slow_on_cpu=True, runs_on_gpu=True)
    assert check_fit(ollama, _caps(gpu_name="NVIDIA GeForce RTX 4070")).summary == "Runs well"
    assert check_fit(ollama, _caps(gpu_name="Intel UHD Graphics 630")).notes == [
        "Slow without a GPU"
    ]
    # A hard blocker outranks the soft note, but the note is still reported.
    fit = check_fit(_spec(slow_on_cpu=True, approx_ram_mb=99999), _caps())
    assert not fit.fits and fit.summary.startswith("Needs") and fit.notes


def test_device_reports_platform_fields(client: TestClient) -> None:
    body = client.get("/api/device/capabilities").json()
    assert body["os_name"] and body["arch"]
    assert body["disk_total_gb"] >= body["disk_free_gb"]
    assert "gpu_name" in body


# --- settings and the cloud switch ---------------------------------------------------


def test_cloud_switch_defaults_to_following_the_key() -> None:
    assert config_store.cloud_enabled() is False
    config_store.set_nvidia_api_key("k")
    assert config_store.cloud_enabled() is True  # saved before the switch existed
    config_store.set_cloud_enabled(False)
    assert config_store.cloud_enabled() is False  # an explicit choice wins


def test_settings_roundtrip_and_unknown_default_is_404(client: TestClient) -> None:
    resp = client.patch("/api/settings", json={"default_model_id": "paddleocr-mobile-en"})
    assert resp.status_code == 200
    assert resp.json()["default_model_id"] == "paddleocr-mobile-en"

    assert client.patch("/api/settings", json={"default_model_id": "nope"}).status_code == 404
    assert client.get("/api/settings").json()["default_model_id"] == "paddleocr-mobile-en"

    cleared = client.patch("/api/settings", json={"default_model_id": ""}).json()
    assert cleared["default_model_id"] is None
    assert client.patch("/api/settings", json={"cloud_enabled": True}).json()["cloud_enabled"]


def test_cloud_models_refused_and_hidden_while_switched_off(client: TestClient) -> None:
    config_store.set_nvidia_api_key("k")
    config_store.set_cloud_enabled(False)

    nim = next(p for p in client.get("/api/platforms").json() if p["id"] == "nvidia-nim")
    assert nim["available"] is False and "switched off" in nim["detail"]

    for path, files in (
        ("/api/ocr/run", {"file": ("a.png", b"x", "image/png")}),
        ("/api/reads", {"files": ("a.png", b"x", "image/png")}),
    ):
        resp = client.post(path, files=files, data={"model_id": "nvidia-nim:some/vlm"})
        assert resp.status_code == 409, path
        assert "switched off" in resp.json()["detail"]


# --- pausable downloads -------------------------------------------------------------


class _SlowEngine:
    """Downloads in ten steps, each waiting for the test to let it continue."""

    def __init__(self) -> None:
        self.downloaded = False
        self.calls = 0
        self.step = threading.Semaphore(0)

    def is_downloaded(self) -> bool:
        return self.downloaded

    def download(self, progress_cb) -> None:
        self.calls += 1
        for pct in range(0, 100, 10):
            progress_cb(float(pct), f"chunk {pct}")
            self.step.acquire(timeout=5)
        self.downloaded = True

    def load(self) -> None:
        pass

    def run(self, image):
        return OcrResult(model_id="slow", lines=[OcrLine(text="hi")], text="hi")

    def delete(self) -> None:
        self.downloaded = False


@pytest.fixture()
def slow_spec():
    engine = _SlowEngine()
    spec = _spec(id="test-slow-model", engine_factory=lambda: engine)
    registry.register(spec)
    yield spec, engine
    registry._models.pop(spec.id, None)


def _start_in_background(client: TestClient, model_id: str) -> threading.Thread:
    # TestClient runs background tasks before the POST returns, so start it on a thread
    # and find the job through the model listing.
    thread = threading.Thread(target=client.post, args=(f"/api/models/{model_id}/download",))
    thread.start()
    return thread


def _active_job(client: TestClient, model_id: str, state: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/models/{model_id}").json()["active_job"]
        if job and job["state"] == state:
            return job
        time.sleep(0.02)
    raise AssertionError(f"no {state} job for {model_id}")


def test_pause_then_resume_download(client: TestClient, slow_spec) -> None:
    _, engine = slow_spec
    first = _start_in_background(client, "test-slow-model")
    job = _active_job(client, "test-slow-model", "downloading")

    resp = client.post(
        "/api/models/test-slow-model/download/pause", params={"job_id": job["job_id"]}
    )
    assert resp.status_code == 200
    engine.step.release()  # let the engine reach its next progress report
    first.join(timeout=10)

    paused = _active_job(client, "test-slow-model", "paused")
    assert paused["job_id"] == job["job_id"]
    assert engine.downloaded is False

    for _ in range(10):
        engine.step.release()
    second = client.post("/api/models/test-slow-model/download").json()["job_id"]
    status = client.get(
        "/api/models/test-slow-model/download/status", params={"job_id": second}
    ).json()
    assert second != job["job_id"]
    assert status["state"] == "done"
    assert engine.calls == 2
    assert client.get("/api/models/test-slow-model").json()["active_job"] is None


def test_pause_unknown_job_is_404(client: TestClient) -> None:
    resp = client.post("/api/models/paddleocr-mobile-en/download/pause", params={"job_id": "x"})
    assert resp.status_code == 404


# --- pages ---------------------------------------------------------------------------


def _png(color: str = "white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 100), color).save(buf, format="PNG")
    return buf.getvalue()


def _tiff(n: int) -> bytes:
    frames = [Image.new("RGB", (120, 80), c) for c in ("white", "gray", "black")[:n]]
    buf = io.BytesIO()
    frames[0].save(buf, format="TIFF", save_all=True, append_images=frames[1:])
    return buf.getvalue()


def _pdf(n: int) -> bytes:
    pdf = pdfium.PdfDocument.new()
    for _ in range(n):
        pdf.new_page(200, 300)
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def test_count_and_iterate_pages_for_each_format() -> None:
    assert count_pages(_png(), "image/png") == 1
    assert count_pages(_tiff(3), "image/tiff") == 3
    assert count_pages(_pdf(2), "application/pdf") == 2
    # Detected by extension too, for clients that send a generic content type.
    assert count_pages(_pdf(2), "application/octet-stream", "scan.PDF") == 2
    assert len(list(iter_pages(_tiff(3), "image/tiff"))) == 3
    pages = list(iter_pages(_pdf(2), "application/pdf"))
    assert len(pages) == 2 and pages[0].dpi == 200


# --- whole-file reads ----------------------------------------------------------------


class _PageEngine:
    """Reports one line per page: the page's mean brightness, so pages are told apart."""

    def is_downloaded(self) -> bool:
        return True

    def download(self, progress_cb) -> None:
        pass

    def load(self) -> None:
        pass

    def run(self, image):
        shade = round(sum(image.convert("L").get_flattened_data()) / (image.width * image.height))
        line = OcrLine(text=f"shade {shade}", confidence=0.9, box=[1, 1, 50, 12])
        return OcrResult(model_id="test-page-model", lines=[line], text=line.text)

    def delete(self) -> None:
        pass


@pytest.fixture()
def page_spec():
    spec = _spec(id="test-page-model", name="Page model", engine_factory=_PageEngine)
    registry.register(spec)
    yield spec
    registry._models.pop(spec.id, None)


def _wait_read(client: TestClient, read_id: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body = client.get(f"/api/reads/{read_id}").json()
        if body["state"] in ("done", "error", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"read never finished: {body}")


@pytest.mark.parametrize("fmt", ["txt", "md", "json", "pdf"])
def test_read_every_page_and_save_in_chosen_format(
    client: TestClient, data_dir: Path, page_spec, fmt: str
) -> None:
    resp = client.post(
        "/api/reads",
        files=[("files", ("scan.tiff", _tiff(3), "image/tiff"))],
        data={"model_id": "test-page-model", "output_format": fmt},
    )
    assert resp.status_code == 202
    read_id = resp.json()["reads"][0]["id"]

    body = _wait_read(client, read_id)
    assert body["state"] == "done", body
    assert body["pages_total"] == 3 and body["pages_done"] == 3
    assert [p["text"] for p in body["pages"]] == ["shade 255", "shade 128", "shade 0"]

    out = Path(body["output_path"])
    assert out.parent == data_dir / "out" and out.suffix == f".{fmt}"
    if fmt == "pdf":
        pdf = pdfium.PdfDocument(out.read_bytes())
        assert len(pdf) == 3
        assert "shade 128" in pdf[1].get_textpage().get_text_range()
    elif fmt == "json":
        saved = json.loads(out.read_text())
        assert [p["page"] for p in saved["pages"]] == [1, 2, 3]
    elif fmt == "md":
        assert out.read_text().startswith("# scan.tiff\n\n## Page 1")
    else:
        assert out.read_text() == "shade 255\n\nshade 128\n\nshade 0\n"


def test_reads_list_newest_first_and_delete(client: TestClient, data_dir, page_spec) -> None:
    ids = []
    for name in ("first.png", "second.png"):
        resp = client.post(
            "/api/reads",
            files=[("files", (name, _png(), "image/png"))],
            data={"model_id": "test-page-model"},
        )
        ids.append(resp.json()["reads"][0]["id"])
    for read_id in ids:
        _wait_read(client, read_id)

    listed = client.get("/api/reads").json()
    assert [r["file_name"] for r in listed] == ["second.png", "first.png"]

    assert client.delete(f"/api/reads/{ids[0]}").status_code == 204
    assert [r["id"] for r in client.get("/api/reads").json()] == [ids[1]]
    assert client.get(f"/api/reads/{ids[0]}").status_code == 404


def test_same_name_never_overwrites_an_earlier_output(
    client: TestClient, data_dir, page_spec
) -> None:
    paths = []
    for _ in range(2):
        read_id = client.post(
            "/api/reads",
            files=[("files", ("a/../notes.png", _png(), "image/png"))],
            data={"model_id": "test-page-model"},
        ).json()["reads"][0]["id"]
        paths.append(_wait_read(client, read_id)["output_path"])
    assert [Path(p).name for p in paths] == ["notes.txt", "notes (2).txt"]


def test_unreadable_file_ends_as_error_and_queue_keeps_going(
    client: TestClient, data_dir, page_spec
) -> None:
    resp = client.post(
        "/api/reads",
        files=[
            ("files", ("broken.png", b"not an image", "image/png")),
            ("files", ("fine.png", _png(), "image/png")),
        ],
        data={"model_id": "test-page-model"},
    )
    broken, fine = resp.json()["reads"]
    assert _wait_read(client, broken["id"])["state"] == "error"
    assert _wait_read(client, fine["id"])["state"] == "done"


def test_unfinished_reads_are_marked_interrupted_on_startup(data_dir, page_spec) -> None:
    from docbox.backend.core import history

    entry = history.create("x.png", "test-page-model", "Page model", "txt")
    history.update(entry.id, state="reading")
    history.mark_interrupted()
    assert history.get(entry.id).state == "error"


def test_startup_leaves_reads_of_other_live_processes_alone(data_dir, page_spec) -> None:
    """The CLI and the MCP server write the same history: a read one of them is still doing
    must not be marked failed when the app starts, but one whose process died is."""
    import subprocess
    import sys

    from docbox.backend.core import history

    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        live = history.create("live.png", "test-page-model", "Page model", "txt")
        history.update(live.id, state="reading", pid=other.pid)
        gone = history.create("gone.png", "test-page-model", "Page model", "txt")
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        history.update(gone.id, state="reading", pid=dead.pid)
        history.mark_interrupted()
        assert history.get(live.id).state == "reading"
        assert history.get(gone.id).state == "error"
    finally:
        other.kill()
        other.wait()


def test_read_ids_cannot_name_paths(client: TestClient, data_dir) -> None:
    assert client.get("/api/reads/..%2F..%2Fsettings").status_code == 404
    assert client.post("/api/reads/notanid/open").status_code == 404


def test_markdown_single_page_has_no_page_headings() -> None:
    text = reader.render_text("a.png", [ReadPage(lines=[], text="hello")], "md")
    assert text == "# a.png\n\nhello\n"


def test_download_serves_only_the_recorded_output(client: TestClient, data_dir, page_spec) -> None:
    read_id = client.post(
        "/api/reads",
        files=[("files", ("scan.png", _png(), "image/png"))],
        data={"model_id": "test-page-model", "output_format": "md"},
    ).json()["reads"][0]["id"]
    body = _wait_read(client, read_id)

    resp = client.get(f"/api/reads/{read_id}/file")
    assert resp.status_code == 200
    saved = Path(body["output_path"]).read_bytes()
    assert b"\r" not in saved  # the same "\n" newlines on every OS, Windows included
    assert resp.content == saved
    assert 'filename="scan.md"' in resp.headers["content-disposition"]

    Path(body["output_path"]).unlink()
    assert client.get(f"/api/reads/{read_id}/file").status_code == 410
    assert client.get("/api/reads/0123/file").status_code == 404


def test_a_finished_read_has_its_pages_saved_before_it_shows_done(data_dir, monkeypatch) -> None:
    from docbox.backend.core import history

    entry = history.create("scan.png", "m", "M", "txt")
    seen = []
    real_save = history._save_index

    def save(entries):
        for e in entries:
            if e.state == "done":
                seen.append(history._detail_path(e.id).exists())
        real_save(entries)

    monkeypatch.setattr(history, "_save_index", save)
    history.finish(entry.id, [ReadPage(lines=[], text="hello")], state="done")
    assert seen == [True]
    assert history.get_detail(entry.id).text == "hello"
