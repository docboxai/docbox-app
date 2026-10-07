"""The published OCRBench scores behind the benchmark graph."""

from __future__ import annotations

from fastapi.testclient import TestClient

from docbox.backend.main import create_app
from docbox.backend.platforms.ollama import RECOMMENDED_VISION_MODELS
from docbox.benchmark.reference import reference


def test_every_score_names_a_catalog_model_and_a_source() -> None:
    data = reference()
    catalog = {f"ollama:{name}" for name, _size, _blurb in RECOMMENDED_VISION_MODELS}
    assert data.models
    for m in data.models:
        assert m.model_id in catalog, m.model_id
        v1, v2 = m.scores.ocrbench_v1, m.scores.ocrbench_v2
        assert v1 or v2
        if v1:
            assert 0 < v1.value <= data.benchmarks["ocrbench_v1"].max
            assert v1.url.startswith("https://") and v1.source
        if v2:
            assert v2.en is not None or v2.zh is not None
            for value in (v2.en, v2.zh):
                assert value is None or 0 < value <= data.benchmarks["ocrbench_v2"].max
            assert v2.url.startswith("https://") and v2.source


def test_reference_route_is_not_taken_for_a_run_id(data_dir) -> None:
    client = TestClient(create_app(), base_url="http://127.0.0.1:8756")
    body = client.get("/api/benchmarks/reference").json()
    assert set(body["benchmarks"]) == {"ocrbench_v1", "ocrbench_v2"}
    assert body["benchmarks"]["ocrbench_v2"]["splits"] == ["en", "zh"]
    assert any(m["model_id"] == "ollama:qwen2.5vl:7b" for m in body["models"])
