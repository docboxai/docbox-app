from __future__ import annotations

import pytest
import requests

from docbox.backend import platforms
from docbox.backend.core import config_store
from docbox.backend.platforms import nvidia_nim, ollama


@pytest.fixture(autouse=True)
def _clean_nvidia_key():
    config_store.clear_nvidia_api_key()
    yield
    config_store.clear_nvidia_api_key()


def test_ollama_status_unavailable_when_not_running(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise requests.ConnectionError("no server")

    monkeypatch.setattr(requests, "get", _raise)
    status = ollama.status()
    assert status["available"] is False
    assert status["id"] == "ollama"


def test_ollama_list_models_filters_to_vision_families(monkeypatch) -> None:
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "models": [
                    {"name": "llama3.2-vision:11b", "size": 8_000_000_000},
                    {"name": "mistral:7b", "size": 4_000_000_000},
                    {"name": "moondream:latest", "size": 1_800_000_000},
                ]
            }

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp())
    specs = ollama.list_models()
    ids = {s.id for s in specs}
    recommended = {f"ollama:{name}" for name, _size, _blurb in ollama.RECOMMENDED_VISION_MODELS}
    # Pulled vision models, plus every recommended one; the pulled llama3.2-vision:11b
    # is also recommended and must appear once, not twice.
    assert ids == {"ollama:moondream:latest"} | recommended
    assert len(specs) == len(ids)
    assert "ollama:mistral:7b" not in ids
    assert all(s.engine == "ollama" and s.prerequisite == "ollama" for s in specs)


def test_ollama_lists_recommended_models_when_not_running(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise requests.ConnectionError("no server")

    monkeypatch.setattr(requests, "get", _raise)
    ids = {s.id for s in ollama.list_models()}
    assert ids == {f"ollama:{n}" for n, _s, _b in ollama.RECOMMENDED_VISION_MODELS}
    assert ollama.get_model_spec("ollama:qwen2.5vl:3b") is not None
    assert ollama.get_model_spec("ollama:not-a-model") is None


def test_ollama_pull_progress_sums_layers_and_reports_success() -> None:
    from docbox.backend.engines.ollama_engine import pull_progress

    stream = [
        b'{"status":"pulling manifest"}',
        b'{"status":"pulling a","digest":"a","total":100,"completed":50}',
        b'{"status":"pulling b","digest":"b","total":300,"completed":0}',
        b'{"status":"pulling b","digest":"b","total":300,"completed":300}',
        b'{"status":"verifying sha256 digest"}',
        b'{"status":"success"}',
    ]
    seen: list[float] = []
    assert pull_progress(stream, lambda pct, _msg: seen.append(pct)) == 100.0
    assert seen[1] == pytest.approx(50.0)
    assert seen[2] == pytest.approx(12.5)
    assert seen[3] == pytest.approx(87.5)


def test_ollama_pull_progress_raises_on_error_line() -> None:
    from docbox.backend.engines.ollama_engine import pull_progress

    with pytest.raises(RuntimeError, match="file does not exist"):
        pull_progress([b'{"error":"pull model manifest: file does not exist"}'], lambda *_: None)


def test_nvidia_nim_status_not_configured_without_key() -> None:
    status = nvidia_nim.status()
    assert status["available"] is False
    assert "API key" in status["detail"]


def test_nvidia_nim_list_models_empty_without_key() -> None:
    assert nvidia_nim.list_models() == []


def test_nvidia_nim_list_models_filters_vision_ids(monkeypatch) -> None:
    config_store.set_nvidia_api_key("test-key")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": [
                    {"id": "meta/llama-3.2-90b-vision-instruct"},
                    {"id": "meta/llama3-70b-instruct"},
                    {"id": "microsoft/phi-3.5-vision-instruct"},
                ]
            }

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp())
    specs = nvidia_nim.list_models()
    ids = {s.id for s in specs}
    assert ids == {
        "nvidia-nim:meta/llama-3.2-90b-vision-instruct",
        "nvidia-nim:microsoft/phi-3.5-vision-instruct",
    }
    assert all(s.engine == "nvidia-nim" for s in specs)


def test_resolve_spec_falls_through_to_dynamic_platforms(monkeypatch) -> None:
    config_store.set_nvidia_api_key("test-key")

    spec = platforms.resolve_spec("nvidia-nim:meta/llama-3.2-90b-vision-instruct")
    assert spec.engine == "nvidia-nim"


def test_resolve_spec_raises_for_unknown_id() -> None:
    with pytest.raises(KeyError):
        platforms.resolve_spec("not-a-real-model")


def test_nvidia_nim_engine_reports_missing_key_clearly() -> None:
    spec = nvidia_nim.get_model_spec("nvidia-nim:some/model")
    assert spec is None  # no key configured

    config_store.set_nvidia_api_key("test-key")
    spec = nvidia_nim.get_model_spec("nvidia-nim:some/model")
    assert spec is not None
    engine = spec.engine_factory()
    assert engine.is_downloaded() is True

    config_store.clear_nvidia_api_key()
    with pytest.raises(RuntimeError, match="API key"):
        engine.download(lambda pct, msg: None)
