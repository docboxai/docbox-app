from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from docbox.backend.core import config_store


@pytest.fixture(autouse=True)
def _clean_nvidia_key():
    config_store.clear_nvidia_api_key()
    yield
    config_store.clear_nvidia_api_key()


def test_list_platforms_includes_ollama_and_nvidia(client: TestClient) -> None:
    resp = client.get("/api/platforms")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert ids == {"ollama", "nvidia-nim"}


def test_nvidia_platform_unavailable_without_key(client: TestClient) -> None:
    resp = client.get("/api/platforms")
    nvidia = next(p for p in resp.json() if p["id"] == "nvidia-nim")
    assert nvidia["available"] is False


def test_set_and_clear_nvidia_api_key(client: TestClient) -> None:
    resp = client.post("/api/platforms/nvidia-nim/api-key", json={"api_key": "test-key-123"})
    assert resp.status_code == 200
    assert resp.json()["configured"] is True
    assert config_store.get_nvidia_api_key() == "test-key-123"

    resp = client.delete("/api/platforms/nvidia-nim/api-key")
    assert resp.status_code == 200
    assert resp.json()["configured"] is False
    assert config_store.get_nvidia_api_key() is None


def test_set_empty_nvidia_api_key_rejected(client: TestClient) -> None:
    resp = client.post("/api/platforms/nvidia-nim/api-key", json={"api_key": "   "})
    assert resp.status_code == 400


def test_models_list_unaffected_when_no_platforms_reachable(client: TestClient) -> None:
    # Ollama isn't running and no NVIDIA key is set in this test environment, so dynamic
    # platform discovery should just contribute nothing rather than error the whole route.
    resp = client.get("/api/models")
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()]
    assert "paddleocr-mobile-en" in ids
