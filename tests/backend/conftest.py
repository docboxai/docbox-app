from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from docbox.backend.engines.ollama_engine import clear_tags_cache
from docbox.backend.main import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _fresh_ollama_status():
    # Ollama's status is cached for a few seconds; don't let one test's (mocked) answer
    # leak into the next.
    clear_tags_cache()
    yield
    clear_tags_cache()
