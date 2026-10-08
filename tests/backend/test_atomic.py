from pathlib import Path

import pytest

from docbox.backend.core import atomic


def _refuse_first(monkeypatch, name: str, times: int) -> list[int]:
    """Make Path.<name> fail like Windows does while another thread has the file open."""
    real = getattr(Path, name)
    calls = [0]

    def flaky(self, *args, **kwargs):
        calls[0] += 1
        if calls[0] <= times:
            raise PermissionError(13, "Access is denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, name, flaky)
    return calls


def test_a_write_waits_out_a_reader_holding_the_file(tmp_path, monkeypatch) -> None:
    target = tmp_path / "run.json"
    target.write_text("old", encoding="utf-8")
    calls = _refuse_first(monkeypatch, "replace", 3)
    atomic.write_text(target, "new")
    assert calls[0] == 4
    monkeypatch.undo()
    assert target.read_text(encoding="utf-8") == "new"
    assert not (tmp_path / "run.json.tmp").exists()


def test_a_read_waits_out_a_write_in_progress(tmp_path, monkeypatch) -> None:
    target = tmp_path / "run.json"
    target.write_text("saved", encoding="utf-8")
    _refuse_first(monkeypatch, "read_text", 3)
    assert atomic.read_text(target) == "saved"


def test_a_file_that_stays_locked_still_fails(tmp_path, monkeypatch) -> None:
    target = tmp_path / "run.json"
    target.write_text("saved", encoding="utf-8")
    monkeypatch.setattr(atomic, "_PAUSE", 0)
    _refuse_first(monkeypatch, "read_text", 10_000)
    with pytest.raises(PermissionError):
        atomic.read_text(target)
