from fastapi.testclient import TestClient


def test_device_capabilities_shape(client: TestClient) -> None:
    resp = client.get("/api/device/capabilities")
    assert resp.status_code == 200
    body = resp.json()

    for key in (
        "ram_total_gb",
        "ram_available_gb",
        "cpu_physical_cores",
        "cpu_logical_cores",
        "disk_free_gb",
    ):
        assert key in body

    assert body["ram_total_gb"] > 0
    assert body["cpu_physical_cores"] >= 1
    assert body["cpu_logical_cores"] >= body["cpu_physical_cores"]
    assert body["disk_free_gb"] >= 0
