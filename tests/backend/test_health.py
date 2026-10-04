from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_cors_allows_the_app_webview_but_not_other_sites(client) -> None:
    def allowed(origin: str) -> str | None:
        resp = client.get("/api/health", headers={"Origin": origin})
        return resp.headers.get("access-control-allow-origin")

    assert allowed("tauri://localhost") == "tauri://localhost"
    assert allowed("http://tauri.localhost") == "http://tauri.localhost"
    assert allowed("http://localhost:1420") == "http://localhost:1420"
    assert allowed("https://evil.example") is None
