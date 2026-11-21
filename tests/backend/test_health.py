from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_cors_allows_no_website_by_default(client) -> None:
    # The desktop app sends no Origin; no web page may read the backend's answers.
    def allowed(origin: str) -> str | None:
        resp = client.get("/api/health", headers={"Origin": origin})
        return resp.headers.get("access-control-allow-origin")

    assert allowed("https://evil.example") is None
    assert allowed("http://localhost:1420") is None
    assert allowed("tauri://localhost") is None
