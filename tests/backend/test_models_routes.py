from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


def test_list_models_includes_paddleocr(client: TestClient) -> None:
    resp = client.get("/api/models")
    assert resp.status_code == 200
    body = resp.json()

    ids = [m["id"] for m in body]
    assert "paddleocr-mobile-en" in ids

    model = next(m for m in body if m["id"] == "paddleocr-mobile-en")
    assert model["engine"] == "paddleocr"
    assert "en" in model["languages"]
    assert "fits" in model["fit"]


def test_get_model_detail(client: TestClient) -> None:
    resp = client.get("/api/models/paddleocr-mobile-en")
    assert resp.status_code == 200
    assert resp.json()["id"] == "paddleocr-mobile-en"


def test_get_unknown_model_is_404(client: TestClient) -> None:
    resp = client.get("/api/models/does-not-exist")
    assert resp.status_code == 404


def test_start_download_unknown_model_is_404(client: TestClient) -> None:
    resp = client.post("/api/models/does-not-exist/download")
    assert resp.status_code == 404


def test_download_status_unknown_job_is_404(client: TestClient) -> None:
    resp = client.get(
        "/api/models/paddleocr-mobile-en/download/status", params={"job_id": "nope"}
    )
    assert resp.status_code == 404


@pytest.mark.real_data_dir
def test_download_already_downloaded_model_reaches_done(client: TestClient) -> None:
    # In this dev environment the model was already fetched during manual testing, so
    # the engine's short-circuit path (`is_downloaded()` -> immediate "done") keeps this
    # test fast and network-free without needing to mock the engine.
    detail = client.get("/api/models/paddleocr-mobile-en").json()
    if not detail["downloaded"]:
        pytest.skip("paddleocr-mobile-en is not downloaded in this environment")

    start = client.post("/api/models/paddleocr-mobile-en/download")
    assert start.status_code == 202
    job_id = start.json()["job_id"]

    deadline = time.monotonic() + 10
    status = None
    while time.monotonic() < deadline:
        status = client.get(
            "/api/models/paddleocr-mobile-en/download/status", params={"job_id": job_id}
        ).json()
        if status["state"] in ("done", "error"):
            break
        time.sleep(0.1)

    assert status is not None
    assert status["state"] == "done"
