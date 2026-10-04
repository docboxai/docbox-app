from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docbox.backend.core import config_store
from docbox.backend.engines.ollama_engine import clear_tags_cache
from docbox.backend.main import create_app


@pytest.fixture()
def client() -> TestClient:
    # The Host the webview and the Vite proxy send; the backend refuses others.
    return TestClient(create_app(), base_url="http://127.0.0.1:8756")


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path: Path, monkeypatch):
    # Tests set and clear the NVIDIA key, the cloud switch and the default model; never
    # let them touch the developer's real settings file.
    monkeypatch.setattr(config_store, "_settings_path", lambda: tmp_path / "settings.json")


@pytest.fixture(autouse=True)
def _fresh_ollama_status():
    # Ollama's status is cached for a few seconds; don't let one test's (mocked) answer
    # leak into the next.
    clear_tags_cache()
    yield
    clear_tags_cache()
