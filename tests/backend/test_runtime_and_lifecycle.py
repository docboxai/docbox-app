from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docbox.backend.api import routes_models
from docbox.backend.core import prerequisites, runtime
from docbox.backend.core.jobs import job_store
from docbox.backend.core.registry import ModelSpec, registry
from docbox.backend.engines.paddleocr_engine import PaddleOcrEngine


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("DOCBOX_DATA_DIR", str(tmp_path))
    return tmp_path


def _wait(client: TestClient, model_id: str, job_id: str) -> list[dict]:
    seen = []
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        s = client.get(f"/api/models/{model_id}/download/status", params={"job_id": job_id}).json()
        seen.append(s)
        if s["state"] in ("done", "error"):
            break
        time.sleep(0.02)
    return seen


# --- runtime: uv commands -----------------------------------------------------


def test_sync_command_managed_mode_skips_dev_and_project(monkeypatch) -> None:
    monkeypatch.setenv("DOCBOX_RUNTIME_MODE", "managed")
    monkeypatch.setenv("DOCBOX_UV", "/opt/uv")
    cmd = runtime.sync_command(["paddle"], inexact=True)
    assert cmd[:3] == ["/opt/uv", "sync", "--frozen"]
    assert "--no-dev" in cmd and "--no-install-project" in cmd
    assert "--inexact" in cmd
    assert cmd[-2:] == ["--extra", "paddle"]


def test_sync_command_dev_mode_keeps_dev_group_and_exact_for_removal(monkeypatch) -> None:
    monkeypatch.delenv("DOCBOX_RUNTIME_MODE", raising=False)
    cmd = runtime.sync_command(["easyocr", "paddle"], inexact=False)
    assert "--no-dev" not in cmd and "--no-install-project" not in cmd
    assert "--inexact" not in cmd
    assert cmd[-4:] == ["--extra", "easyocr", "--extra", "paddle"]


def test_installed_extras_detects_paddle_in_dev_env() -> None:
    # The dev env is synced with `--extra paddle` (see CLAUDE.md).
    assert "paddle" in runtime.installed_extras()


def test_lockfile_installs_only_one_opencv_distribution() -> None:
    # Several OpenCV wheels install the same `cv2` package; with two of them locked,
    # installing/removing one engine overwrote/deleted files another engine needed.
    import tomllib

    lock = tomllib.loads((runtime.project_dir() / "uv.lock").read_text(encoding="utf-8"))
    cv2_wheels = {"opencv-python", "opencv-python-headless", "opencv-contrib-python-headless"}
    for package in lock["package"]:
        for dep in package.get("dependencies", []):
            if dep["name"] in cv2_wheels:
                assert "never" in dep.get("marker", ""), (
                    f"{package['name']} pulls in {dep['name']} next to opencv-contrib-python"
                )


# --- staged download job ---------------------------------------------------------


class _FakeEngine:
    def __init__(self) -> None:
        self.downloaded = False

    def is_downloaded(self) -> bool:
        return self.downloaded

    def download(self, progress_cb) -> None:
        progress_cb(50.0, "half")
        self.downloaded = True

    def load(self) -> None:
        pass

    def run(self, image):
        raise NotImplementedError

    def delete(self) -> None:
        self.downloaded = False


@pytest.fixture()
def fake_spec():
    engine = _FakeEngine()
    spec = ModelSpec(
        id="test-fake-model",
        name="Fake",
        engine="fake",
        description="",
        languages=["en"],
        approx_download_mb=1,
        approx_ram_mb=1,
        min_disk_mb=1,
        engine_factory=lambda: engine,
        requires_extra="easyocr",
    )
    registry.register(spec)
    yield spec, engine
    registry._models.pop(spec.id, None)


def test_download_installs_engine_then_weights(client, fake_spec, monkeypatch) -> None:
    installed: list[str] = []
    monkeypatch.setattr(
        runtime, "extra_installed", lambda name: name in installed or name == "paddle"
    )
    monkeypatch.setattr(runtime, "installed_extras", lambda: {"paddle", *installed})

    def fake_ensure(name, cb):
        cb(50.0, "uv: installing")
        installed.append(name)

    monkeypatch.setattr(runtime, "ensure_extra", fake_ensure)

    assert client.get("/api/models/test-fake-model").json()["status"] == "needs_engine"
    job_id = client.post("/api/models/test-fake-model/download").json()["job_id"]
    seen = _wait(client, "test-fake-model", job_id)

    assert seen[-1]["state"] == "done"
    assert installed == ["easyocr"]
    assert client.get("/api/models/test-fake-model").json()["status"] == "ready"


def test_download_needing_missing_prerequisite_is_409(client, fake_spec, monkeypatch) -> None:
    spec, _engine = fake_spec
    registry.register(ModelSpec(**{**spec.__dict__, "requires_extra": None,
                                   "prerequisite": "tesseract"}))
    monkeypatch.setattr(prerequisites, "is_satisfied", lambda _pid: False)

    assert client.get("/api/models/test-fake-model").json()["status"] == "needs_prerequisite"
    resp = client.post("/api/models/test-fake-model/download")
    assert resp.status_code == 409
    assert "Tesseract" in resp.json()["detail"]


def test_install_failure_surfaces_as_job_error(client, fake_spec, monkeypatch) -> None:
    monkeypatch.setattr(runtime, "extra_installed", lambda name: False)

    def boom(name, cb):
        raise runtime.EngineInstallError("Package install failed:\nno network")

    monkeypatch.setattr(runtime, "ensure_extra", boom)
    job_id = client.post("/api/models/test-fake-model/download").json()["job_id"]
    final = _wait(client, "test-fake-model", job_id)[-1]
    assert final["state"] == "error"
    assert "no network" in final["message"]


# --- deletion ---------------------------------------------------------------------


def test_delete_keeps_paddle_dirs_shared_with_other_downloaded_models(data_dir) -> None:
    official = data_dir / "models" / "paddlex_cache" / "official_models"
    for name in ("PP-OCRv5_server_det", "latin_PP-OCRv5_mobile_rec", "en_PP-OCRv5_mobile_rec"):
        (official / name).mkdir(parents=True)

    latin = registry.get("paddleocr-latin").engine_factory()
    accurate = registry.get("paddleocr-accurate-en").engine_factory()
    assert isinstance(latin, PaddleOcrEngine)
    assert latin.is_downloaded() and accurate.is_downloaded()

    latin.delete()
    assert not (official / "latin_PP-OCRv5_mobile_rec").exists()
    assert (official / "PP-OCRv5_server_det").exists()  # accurate-en still needs it
    assert accurate.is_downloaded()

    accurate.delete()
    assert not (official / "PP-OCRv5_server_det").exists()


def test_delete_route_204_and_409_while_downloading(client, fake_spec) -> None:
    _spec, engine = fake_spec
    engine.downloaded = True
    job = job_store.create("test-fake-model")
    job_store.update(job.job_id, state="downloading")
    assert client.delete("/api/models/test-fake-model").status_code == 409

    job_store.update(job.job_id, state="done")
    assert client.delete("/api/models/test-fake-model").status_code == 204
    assert engine.downloaded is False


def test_delete_cloud_model_is_400(client, monkeypatch) -> None:
    from docbox.backend.core import config_store

    config_store.set_nvidia_api_key("test-key")
    try:
        resp = client.delete("/api/models/nvidia-nim:some-model")
        assert resp.status_code == 400
        assert "cloud" in resp.json()["detail"]
    finally:
        config_store.clear_nvidia_api_key()


# --- prerequisites -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("os_release", "expected"),
    [
        ('ID=ubuntu\nID_LIKE=debian\n', "sudo apt install -y tesseract-ocr"),
        ('ID="fedora"\n', "sudo dnf install -y tesseract"),
        ("ID=manjaro\nID_LIKE=arch\n", "sudo pacman -S --needed tesseract"),
    ],
)
def test_linux_tesseract_command_matches_distro(monkeypatch, os_release, expected) -> None:
    monkeypatch.setattr(prerequisites.sys, "platform", "linux")
    pairs = (line.split("=", 1) for line in os_release.splitlines() if "=" in line)
    parsed = {k: v.strip('"') for k, v in pairs}
    monkeypatch.setattr(prerequisites, "_os_release", lambda: parsed)
    assert prerequisites.manual_commands("tesseract") == [expected]


def test_prerequisites_endpoint_shape(client) -> None:
    body = client.get("/api/prerequisites").json()
    assert {p["id"] for p in body} == {"ollama", "tesseract"}
    for p in body:
        assert p["state"] in ("ready", "installed", "missing")
        assert p["commands"]


def test_engine_storage_endpoint(client, data_dir) -> None:
    body = client.get("/api/engines/storage").json()
    assert body["data_dir"] == str(data_dir)
    assert body["models_bytes"] == 0  # fresh data dir
    ids = {e["id"] for e in body["engines"]}
    assert ids == set(runtime.EXTRAS)


def test_uninstall_unknown_engine_is_404(client) -> None:
    assert client.delete("/api/engines/not-an-engine").status_code == 404


def test_scaled_progress_maps_into_stage_range() -> None:
    job = job_store.create("scaled-test")
    routes_models._scaled(job.job_id, "installing", 0, 40)(50.0, "x")
    assert job_store.get(job.job_id).progress_pct == pytest.approx(20.0)
