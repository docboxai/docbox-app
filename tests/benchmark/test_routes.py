"""/api/benchmarks: what the app's Benchmarks view calls."""

from __future__ import annotations

import io
import time

from fastapi.testclient import TestClient
from PIL import Image

from docbox.backend.main import create_app
from docbox.benchmark import store


def _client() -> TestClient:
    return TestClient(create_app(), base_url="http://127.0.0.1:8756")


def _png(n: int, fakes) -> bytes:
    buf = io.BytesIO()
    fakes.page_image(n).save(buf, format="PNG")
    return buf.getvalue()


def _wait(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 60
    while True:
        run = client.get(f"/api/benchmarks/{run_id}").json()
        if run["state"] not in ("queued", "running"):
            return run
        assert time.monotonic() < deadline
        time.sleep(0.1)


def _start(client: TestClient, fakes, **form) -> dict:
    files = [
        ("files", ("Invoices/march/invoice.png", _png(1, fakes), "image/png")),
        ("files", ("Invoices/march/invoice.gt.txt", fakes.TEXTS[1].encode(), "text/plain")),
        ("files", ("Invoices/scan.png", _png(2, fakes), "image/png")),
    ]
    resp = client.post("/api/benchmarks", files=files,
                       data={"model_ids": "fake-good,fake-sloppy", **form})
    assert resp.status_code == 202, resp.text
    return resp.json()


def test_upload_a_folder_run_and_compare(fakes) -> None:
    client = _client()
    started = _start(client, fakes)
    assert started["name"] == "Invoices"  # named after the dropped folder
    assert {f["id"] for f in started["files"]} == {"Invoices/march/invoice.png", "Invoices/scan.png"}
    assert {f["id"]: f["has_reference"] for f in started["files"]}["Invoices/march/invoice.png"]

    run = _wait(client, started["id"])
    assert run["state"] == "done" and run["summary"]["best_model_id"] == "fake-good"
    assert started["id"] in [r["id"] for r in client.get("/api/benchmarks").json()]

    page = client.get(f"/api/benchmarks/{run['id']}/page",
                      params={"file_id": "Invoices/march/invoice.png"}).json()
    assert {r["model_id"]: r["slips"] for r in page["reads"]} == {"fake-good": 0, "fake-sloppy": 2}

    image = client.get(f"/api/benchmarks/{run['id']}/image",
                       params={"file_id": "Invoices/scan.png", "page": 1})
    assert image.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(image.content)).size == (120, 60)

    report = client.get(f"/api/benchmarks/{run['id']}/report", params={"format": "csv"})
    assert report.text.startswith("model_id,") and "attachment" in report.headers[
        "content-disposition"]


def test_upload_names_cant_escape_the_run_folder(fakes) -> None:
    client = _client()
    files = [("files", ("../../evil/x.png", _png(1, fakes), "image/png")),
             ("files", ("C:\\Windows\\y.png", _png(1, fakes), "image/png"))]
    run = client.post("/api/benchmarks", files=files, data={"model_ids": "fake-good"}).json()
    inputs = store.run_dir(run["id"]) / "inputs"
    saved = [p.resolve() for p in store.root().parent.rglob("*.png")]
    assert len(saved) == 2
    assert all(p.is_relative_to(inputs.resolve()) for p in saved)
    assert (inputs / "evil" / "x.png").exists()
    _wait(client, run["id"])


def test_bad_start_leaves_no_folder(fakes) -> None:
    client = _client()
    before = set(store.root().iterdir())
    resp = client.post("/api/benchmarks", data={"model_ids": "no-such-model"},
                       files=[("files", ("a.png", _png(1, fakes), "image/png"))])
    assert resp.status_code == 404
    assert set(store.root().iterdir()) == before


def test_a_bad_name_late_in_the_upload_leaves_no_folder(fakes) -> None:
    client = _client()
    before = set(store.root().iterdir())
    resp = client.post("/api/benchmarks", files=[
        ("files", ("Invoices/a.png", _png(1, fakes), "image/png")),
        ("files", ("Invoices/b.png", _png(2, fakes), "image/png")),
        ("files", ("../ /..", _png(1, fakes), "image/png")),  # sanitises to nothing
    ])
    assert resp.status_code == 400
    assert set(store.root().iterdir()) == before


def test_rerun_cancel_and_delete(fakes) -> None:
    client = _client()
    run = _wait(client, _start(client, fakes)["id"])
    assert client.post(f"/api/benchmarks/{run['id']}/cancel").status_code == 409

    again = client.post(f"/api/benchmarks/{run['id']}/rerun")
    assert again.status_code == 202
    again = _wait(client, again.json()["id"])
    assert again["id"] != run["id"] and again["summary"]["best_model_id"] == "fake-good"

    assert client.delete(f"/api/benchmarks/{run['id']}").status_code == 204
    assert client.get(f"/api/benchmarks/{run['id']}").status_code == 404
    # Uploaded files were copied into the re-run: it can still show and re-run its pages.
    assert client.get(f"/api/benchmarks/{again['id']}/image",
                      params={"file_id": "Invoices/scan.png"}).status_code == 200
    third = client.post(f"/api/benchmarks/{again['id']}/rerun")
    assert third.status_code == 202
    assert _wait(client, third.json()["id"])["state"] == "done"


def test_unknown_ids(data_dir) -> None:
    client = _client()
    assert client.get("/api/benchmarks/20990101-000000-abcdef").status_code == 404
    assert client.get("/api/benchmarks/..%2F..%2Fetc").status_code == 404
