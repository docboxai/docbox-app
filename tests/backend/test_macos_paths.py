"""A Finder-launched macOS app has no Homebrew folders on PATH; DocBox looks there itself."""

from __future__ import annotations

import sys
from pathlib import Path

from docbox.backend.core import prerequisites
from docbox.backend.engines import tesseract_engine


def _program(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("")
    return path


def test_tesseract_found_in_homebrew_on_macos(tmp_path: Path, monkeypatch) -> None:
    homebrew, intel = tmp_path / "opt-homebrew-bin", tmp_path / "usr-local-bin"
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(tesseract_engine.shutil, "which", lambda _name: None)
    monkeypatch.setattr(tesseract_engine, "MACOS_BIN_DIRS", (homebrew, intel))

    assert tesseract_engine.find_tesseract_binary() is None
    expected = _program(intel, "tesseract")
    assert tesseract_engine.find_tesseract_binary() == str(expected)


def test_tesseract_not_searched_outside_path_on_linux(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(tesseract_engine.shutil, "which", lambda _name: None)
    monkeypatch.setattr(tesseract_engine, "MACOS_BIN_DIRS", (tmp_path,))
    _program(tmp_path, "tesseract")
    assert tesseract_engine.find_tesseract_binary() is None


def test_ollama_found_in_homebrew_or_the_app_on_macos(tmp_path: Path, monkeypatch) -> None:
    homebrew, app = tmp_path / "opt-homebrew-bin", tmp_path / "Ollama.app"
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(prerequisites.shutil, "which", lambda _name: None)
    monkeypatch.setattr(prerequisites, "MACOS_BIN_DIRS", (homebrew,))
    monkeypatch.setattr(prerequisites, "_OLLAMA_MAC_APP", app)

    assert prerequisites._ollama_binary() is None
    bundled = _program(app / "Contents" / "Resources", "ollama")
    assert prerequisites._ollama_binary() == str(bundled)
    brewed = _program(homebrew, "ollama")
    assert prerequisites._ollama_binary() == str(brewed)
