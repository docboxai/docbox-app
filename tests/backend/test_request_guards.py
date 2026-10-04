"""Guards against other websites using the localhost backend: DNS rebinding (Host
check) and cross-site form posts (Origin / client header), plus the review fixes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docbox.backend.api import routes_engines, routes_models
from docbox.backend.core import history
from docbox.backend.core.client_header import CLIENT_HEADER
from docbox.backend.core.jobs import DownloadJobStore, JobPaused, job_store
from docbox.backend.engines import remote_engine
from docbox.backend.main import create_app

EVIL = "https://evil.example"


# --- Host header (DNS rebinding) ------------------------------------------------------


@pytest.mark.parametrize("host", ["attacker.example:8756", "testserver", "192.168.1.5:8756"])
def test_unknown_host_is_refused(host: str) -> None:
    c = TestClient(create_app(), base_url=f"http://{host}")
    assert c.get("/api/reads").status_code == 400
    assert c.get("/api/health").status_code == 400


@pytest.mark.parametrize("host", ["127.0.0.1:8756", "localhost:8756", "127.0.0.1:51234"])
def test_app_hosts_are_allowed(host: str) -> None:
    assert TestClient(create_app(), base_url=f"http://{host}").get("/api/health").status_code == 200


def test_extra_hosts_come_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("DOCBOX_ALLOWED_HOSTS", "paddleocr, tesseract")
    app = create_app()
    assert TestClient(app, base_url="http://paddleocr:8756").get("/api/health").status_code == 200
    assert TestClient(app, base_url="http://easyocr:8756").get("/api/health").status_code == 400


# --- cross-site writes -----------------------------------------------------------------


@pytest.fixture()
def opened(monkeypatch) -> list[Path]:
    calls: list[Path] = []
    monkeypatch.setattr(routes_engines, "open_path", calls.append)
    return calls


def test_cross_site_form_post_is_refused_before_it_runs(client: TestClient, opened) -> None:
    resp = client.post("/api/engines/storage/open", headers={"Origin": EVIL})
    assert resp.status_code == 403
    assert opened == []


@pytest.mark.parametrize(
    "headers",
    [
        {CLIENT_HEADER: "app", "Origin": "https://den-home.example.ts.net"},  # app via proxy
        {},  # curl, scripts, RemoteEngine: no Origin
        {"Origin": "http://127.0.0.1:8756"},  # the backend's own Swagger UI
    ],
)
def test_legitimate_writes_go_through(client: TestClient, opened, headers) -> None:
    assert client.post("/api/engines/storage/open", headers=headers).status_code == 204
    assert len(opened) == 1


def test_reads_are_not_guarded_by_origin(client: TestClient) -> None:
    # GETs change nothing; CORS already hides their responses from other origins.
    assert client.get("/api/reads", headers={"Origin": EVIL}).status_code == 200


def test_other_origins_cannot_preflight_the_client_header(client: TestClient) -> None:
    resp = client.options(
        "/api/reads",
        headers={
            "Origin": EVIL,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": CLIENT_HEADER,
        },
    )
    assert resp.headers.get("access-control-allow-origin") is None


def test_remote_engine_sends_the_client_header(monkeypatch) -> None:
    seen: dict = {}

    class _Resp:
        ok = True
        status_code = 200

        def json(self):
            return {"job_id": "j"}

    def fake_request(method, url, *, timeout, headers, **kwargs):
        seen.update(headers)
        return _Resp()

    monkeypatch.setattr(remote_engine.requests, "request", fake_request)
    engine = remote_engine.RemoteEngine(base_url="http://paddleocr:8756", model_id="m")
    engine._request("POST", "/api/models/m/download", timeout=1)
    assert seen[CLIENT_HEADER]


# --- startup work only when a server starts ---------------------------------------------


def test_building_the_app_leaves_read_history_alone(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DOCBOX_DATA_DIR", str(tmp_path))
    entry = history.create("x.png", "m", "M", "txt")
    history.update(entry.id, state="reading")

    create_app()
    assert history.get(entry.id).state == "reading"

    with TestClient(create_app(), base_url="http://127.0.0.1"):  # runs the lifespan
        pass
    assert history.get(entry.id).state == "error"


# --- downloads: pause at the end, progress direction ------------------------------------


def test_pause_requested_at_100_percent_does_not_pause() -> None:
    job = job_store.create("test-pause-at-end")
    job_store.request_pause(job.job_id)
    cb = routes_models._scaled(job.job_id, "downloading", 0, 100)
    with pytest.raises(JobPaused):
        cb(50.0, "half")
    cb(100.0, "ready")  # files are in place: finishing must not be reported as paused


def test_progress_never_moves_backwards_within_a_job() -> None:
    store = DownloadJobStore()
    job = store.create("m", progress_pct=55.0)  # resumed at the paused percentage
    store.update(job.job_id, state="downloading", progress_pct=0.0)
    assert store.get(job.job_id).progress_pct == 55.0
    store.update(job.job_id, progress_pct=70.0)
    assert store.get(job.job_id).progress_pct == 70.0
