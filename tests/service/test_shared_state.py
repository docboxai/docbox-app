"""What lets the CLI, the MCP server and the app's backend share one data dir: which
folder is picked, locks between processes, and installing engines without a project."""

from __future__ import annotations

import multiprocessing
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from docbox.backend.core import config_store, history, locks, paths, runtime
from docbox.service import models as service_models
from docbox.service.errors import Conflict

ROOT = Path(__file__).resolve().parents[2]


# --- which data dir -----------------------------------------------------------------


def test_env_var_wins(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOCBOX_DATA_DIR", str(tmp_path / "x"))
    assert paths.get_data_dir() == tmp_path / "x"


def test_desktop_app_folder_is_shared_when_it_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DOCBOX_DATA_DIR", raising=False)
    app_dir = tmp_path / "io.github.docboxai.docbox"
    monkeypatch.setattr(paths, "desktop_app_data_dir", lambda: app_dir)
    monkeypatch.setattr(paths.platformdirs, "user_data_dir", lambda **_: str(tmp_path / "own"))
    assert paths.get_data_dir() == tmp_path / "own"  # no app here yet
    app_dir.mkdir()
    assert paths.get_data_dir() == app_dir


def test_desktop_app_folder_matches_tauri_identifier() -> None:
    import json

    conf = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    assert paths.APP_IDENTIFIER == conf["identifier"]
    assert paths.desktop_app_data_dir().name == conf["identifier"]


# --- locks between processes --------------------------------------------------------


def _hold_model_lock(data_dir: str, model_id: str, ready, release) -> None:
    import os

    os.environ["DOCBOX_DATA_DIR"] = data_dir
    from docbox.backend.core import locks as child_locks

    with child_locks.model_lock(model_id):
        ready.set()
        release.wait(10)


def test_installing_a_model_another_process_is_installing_is_a_conflict(fake_model, data_dir):
    ctx = multiprocessing.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_hold_model_lock, args=(str(data_dir), fake_model.id, ready, release))
    child.start()
    try:
        assert ready.wait(20)
        with pytest.raises(Conflict, match="already being installed"):
            service_models.install_model(fake_model.id)
    finally:
        release.set()
        child.join(10)
    service_models.install_model(fake_model.id)  # free again
    assert fake_model.engine_factory().is_downloaded()


def _add_history(data_dir: str, settings: str, n: int) -> None:
    import os

    os.environ["DOCBOX_DATA_DIR"] = data_dir
    from docbox.backend.core import config_store as cs
    from docbox.backend.core import history as h

    cs._settings_path = lambda: Path(settings)
    for i in range(n):
        h.create(f"file-{os.getpid()}-{i}.png", "m", "M", "txt")


def test_history_writes_from_two_processes_are_not_lost(data_dir, tmp_path) -> None:
    ctx = multiprocessing.get_context("spawn")
    procs = [
        ctx.Process(target=_add_history, args=(str(data_dir), str(tmp_path / "s.json"), 25))
        for _ in range(3)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    assert len(history.list_reads()) == 75


def test_settings_updates_keep_each_other(data_dir) -> None:
    config_store.set_default_model_id("a")
    config_store.set_cloud_enabled(True)
    config_store.set_output_dir("/tmp/x")
    assert config_store.get_default_model_id() == "a"
    assert config_store.cloud_enabled() is True
    config_store.set_default_model_id(None)
    assert config_store.get_default_model_id() is None
    assert config_store.cloud_enabled() is True


def test_model_lock_names_are_safe(data_dir) -> None:
    lock = locks.model_lock("ollama:qwen2.5vl:3b/../x")
    assert Path(lock.lock_file).parent == data_dir / "locks"


# --- tool mode (a standalone docbox, no project to sync) ----------------------------


def test_mode_detection(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("DOCBOX_RUNTIME_MODE", raising=False)
    assert runtime.mode() == "dev"  # this checkout has pyproject.toml + uv.lock
    monkeypatch.setattr(runtime, "project_dir", lambda: tmp_path)
    assert runtime.mode() == "tool"
    monkeypatch.setenv("DOCBOX_RUNTIME_MODE", "managed")
    assert runtime.mode() == "managed"


def test_tool_mode_installs_with_pins_into_this_python(monkeypatch) -> None:
    monkeypatch.setenv("DOCBOX_UV", "uv")
    cmd = runtime.pip_install_command("easyocr")
    assert cmd[:6] == ["uv", "pip", "install", "--python", sys.executable, "--constraints"]
    assert Path(cmd[6]).name == "constraints.txt" and Path(cmd[6]).exists()
    assert "--overrides" in cmd and "https://download.pytorch.org/whl/cpu" in cmd
    assert any(r.startswith("torch") for r in cmd) and "easyocr>=1.7" in cmd


def test_tool_mode_install_runs_pip_not_sync(monkeypatch) -> None:
    ran: list[list[str]] = []
    monkeypatch.setenv("DOCBOX_RUNTIME_MODE", "tool")
    monkeypatch.setenv("DOCBOX_UV", "uv")
    monkeypatch.setattr(runtime, "extra_installed", lambda name: bool(ran))
    monkeypatch.setattr(runtime, "run_streaming", lambda cmd, cb, **_: ran.append(cmd))
    monkeypatch.setattr(runtime, "_write_state", lambda **_: None)
    runtime.ensure_extra("easyocr", lambda *_: None)
    assert ran[0][1:3] == ["pip", "install"]


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_pins_match_the_lock_file(tmp_path) -> None:
    """scripts/export_pins.sh output is committed; regenerate it after changing uv.lock."""
    exported = subprocess.run(
        ["uv", "export", "--frozen", "--all-extras", "--no-dev", "--no-emit-project",
         "--no-hashes", "--no-header", "--no-annotate"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    pins = ROOT / "src" / "docbox" / "backend" / "core" / "pins" / "constraints.txt"
    assert pins.read_text(encoding="utf-8").replace("\r\n", "\n") == exported.replace("\r\n", "\n"), (
        "pins are stale: run scripts/export_pins.sh"
    )
