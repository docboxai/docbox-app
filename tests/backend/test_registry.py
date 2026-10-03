from docbox.backend.core.registry import ModelRegistry, ModelSpec, check_fit
from docbox.backend.schemas import DeviceCapabilities


def _spec(**overrides) -> ModelSpec:
    defaults = {
        "id": "dummy",
        "name": "Dummy Model",
        "engine": "dummy",
        "description": "test fixture",
        "languages": ["en"],
        "approx_download_mb": 10,
        "approx_ram_mb": 500,
        "min_disk_mb": 100,
        "engine_factory": lambda: None,
    }
    defaults.update(overrides)
    return ModelSpec(**defaults)


def test_register_get_list() -> None:
    registry = ModelRegistry()
    spec = _spec()
    registry.register(spec)

    assert registry.get("dummy") is spec
    assert registry.list() == [spec]


def test_get_unknown_model_raises_key_error() -> None:
    registry = ModelRegistry()
    try:
        registry.get("nope")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_check_fit_passes_when_resources_sufficient() -> None:
    spec = _spec(approx_ram_mb=500, min_disk_mb=100)
    caps = DeviceCapabilities(
        ram_total_gb=16,
        ram_available_gb=8,
        cpu_physical_cores=4,
        cpu_logical_cores=8,
        disk_free_gb=50,
    )
    result = check_fit(spec, caps)
    assert result.fits is True
    assert result.reasons == []


def test_check_fit_flags_insufficient_ram_and_disk() -> None:
    spec = _spec(approx_ram_mb=8000, min_disk_mb=100_000)
    caps = DeviceCapabilities(
        ram_total_gb=4,
        ram_available_gb=1,
        cpu_physical_cores=2,
        cpu_logical_cores=4,
        disk_free_gb=1,
    )
    result = check_fit(spec, caps)
    assert result.fits is False
    assert len(result.reasons) == 2
