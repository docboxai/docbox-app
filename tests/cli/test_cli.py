"""The `docbox` command, run in-process: --json output, exit codes and confirmations."""

from __future__ import annotations

import json

import pytest

from docbox.backend.core import history
from docbox.cli.main import main

FAKE = "test-fake"


def run_json(capsys, *argv: str) -> tuple[int, dict | list, str]:
    code = main(["--json", *argv])
    captured = capsys.readouterr()
    return code, (json.loads(captured.out) if captured.out.strip() else None), captured.err


def test_help_and_version(capsys) -> None:
    assert main(["--help"]) == 0
    assert "benchmark" in capsys.readouterr().out
    assert main(["--version"]) == 0


def test_unknown_command_is_usage_error(capsys) -> None:
    assert main(["frobnicate"]) == 2


def test_device_reports_data_dir(capsys, data_dir) -> None:
    code, body, _ = run_json(capsys, "device")
    assert code == 0
    assert body["data_dir"] == str(data_dir)
    assert body["device"]["cpu_logical_cores"] >= 1


def test_json_flag_works_after_the_command(capsys, data_dir) -> None:
    assert main(["device", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data_dir"] == str(data_dir)


def test_models_list_includes_catalog_and_filters_ready(capsys, fake_model) -> None:
    code, body, _ = run_json(capsys, "models", "list")
    assert code == 0
    ids = {m["id"] for m in body}
    assert {"paddleocr-mobile-en", FAKE} <= ids

    code, body, _ = run_json(capsys, "models", "list", "--ready")
    assert all(m["status"] == "ready" for m in body)
    assert FAKE not in {m["id"] for m in body}


def test_install_then_remove(capsys, fake_model, monkeypatch) -> None:
    code, body, _ = run_json(capsys, "models", "install", FAKE)
    assert code == 0 and body["status"] == "ready"

    code, body, _ = run_json(capsys, "models", "remove", FAKE, "--yes")
    assert code == 0 and body == {"removed": FAKE}
    assert not fake_model.engine_factory().is_downloaded()


def test_remove_without_yes_and_without_a_terminal_refuses(capsys, installed_fake, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    code, _, err = run_json(capsys, "models", "remove", FAKE)
    assert code == 1
    assert json.loads(err)["error"]["code"] == "invalid"
    assert installed_fake.engine_factory().is_downloaded()


def test_unknown_model_is_not_found(capsys, data_dir) -> None:
    code, _, err = run_json(capsys, "models", "show", "no-such-model")
    assert code == 1
    assert json.loads(err)["error"] == {"code": "not_found", "detail": "Unknown model: no-such-model"}


def test_read_saves_output_and_records_history(capsys, installed_fake, sample_image, tmp_path):
    out_dir = tmp_path / "saved"
    code, body, _ = run_json(
        capsys, "read", str(sample_image), "--model", FAKE, "--format", "md", "--out", str(out_dir)
    )
    assert code == 0
    [result] = body["files"]
    assert result["pages"][0]["text"].startswith("Total due")
    assert "lines" not in result["pages"][0]
    saved = out_dir / "invoice.md"
    assert result["output_path"] == str(saved)
    assert "Ref INV-0312" in saved.read_text()
    assert history.get(result["read_id"]).state == "done"


def test_read_a_folder_with_lines(capsys, installed_fake, sample_image, tmp_path):
    (sample_image.parent / "notes.txt").write_text("not an image")
    code, body, _ = run_json(
        capsys, "read", str(sample_image.parent), "-m", FAKE, "--lines", "--out", str(tmp_path)
    )
    assert code == 0
    assert [f["file"] for f in body["files"]] == [str(sample_image)]
    assert body["files"][0]["pages"][0]["lines"][0]["confidence"] == 0.9


def test_read_with_a_model_not_installed_is_a_conflict(capsys, fake_model, sample_image):
    code, _, err = run_json(capsys, "read", str(sample_image), "-m", FAKE)
    assert code == 1
    assert "not downloaded" in json.loads(err)["error"]["detail"]


def test_read_needs_a_model(capsys, data_dir, sample_image) -> None:
    code, _, err = run_json(capsys, "read", str(sample_image))
    assert code == 1
    assert "--model" in json.loads(err)["error"]["detail"]


def test_read_missing_file(capsys, installed_fake, tmp_path) -> None:
    code, _, err = run_json(capsys, "read", str(tmp_path / "nope.png"), "-m", FAKE)
    assert code == 1
    assert json.loads(err)["error"]["code"] == "not_found"


def test_cloud_model_blocked_exit_code(capsys, data_dir) -> None:
    code, _, err = run_json(capsys, "models", "install", "nvidia-nim:anything")
    assert code == 4
    assert json.loads(err)["error"]["code"] == "blocked"


def test_settings_roundtrip(capsys, fake_model) -> None:
    code, body, _ = run_json(capsys, "settings", "set", "default-model", FAKE)
    assert code == 0 and body["default_model_id"] == FAKE
    code, body, _ = run_json(capsys, "settings", "set", "cloud", "on")
    assert body["cloud_enabled"] is True
    code, body, _ = run_json(capsys, "settings", "set", "default-model", "none")
    assert body["default_model_id"] is None


@pytest.mark.parametrize("value", ["maybe", "1"])
def test_settings_cloud_rejects_other_values(capsys, data_dir, value) -> None:
    code, _, _ = run_json(capsys, "settings", "set", "cloud", value)
    assert code == 1


def test_engines_list(capsys, data_dir) -> None:
    code, body, _ = run_json(capsys, "engines", "list")
    assert code == 0
    assert {e["id"] for e in body["engines"]} == {"paddle", "easyocr"}


def test_json_output_stays_clean_when_an_engine_prints(fakes, tmp_path) -> None:
    """Engines run in the CLI's own process and print to stdout (fake-noisy does, like
    PaddleOCR loading); `--json` output must still parse."""
    import os
    import subprocess
    import sys

    image = tmp_path / "page.png"
    fakes.page_image(1).save(image)
    proc = subprocess.run(
        [sys.executable, "-m", "docbox.cli", "read", str(image), "-m", "fake-noisy",
         "--out", str(tmp_path / "out"), "--json"],
        capture_output=True, text=True, env=os.environ, timeout=120, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert "library chatter" not in proc.stdout
    assert "library chatter" in proc.stderr
    assert result
