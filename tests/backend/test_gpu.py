"""Reading on an NVIDIA graphics card: whether this computer can (core/gpu.py::support), which
models do (choose), falling back to the processor, the engines' graphics-card builds
(core/runtime.py) and the settings and routes around them. Nothing here runs a model or
touches CUDA: engines, nvidia-smi and uv are faked."""

from __future__ import annotations

import sys

import pytest
from PIL import Image

from docbox.backend.core import config_store, device, engine_cache, gpu, runtime
from docbox.backend.core.registry import ModelSpec, inference_device
from docbox.backend.engines.paddleocr_engine import PaddleOcrEngine
from docbox.backend.schemas import DeviceCapabilities
from docbox.service import engines as engines_service


@pytest.fixture(autouse=True)
def _no_fallbacks():
    gpu.clear_fallbacks()
    yield
    gpu.clear_fallbacks()


def _gpu(**overrides) -> device.NvidiaGpu:
    base = {"name": "NVIDIA GeForce RTX 3060", "memory_gb": 12.0,
            "driver_version": "595.91.07", "cuda_version": "13.2", "compute_capability": "8.6"}
    return device.NvidiaGpu(**{**base, **overrides})


def _spec(**overrides) -> ModelSpec:
    base = {
        "id": "t", "name": "T", "engine": "PaddleOCR", "description": "", "languages": ["en"],
        "approx_download_mb": 1, "approx_ram_mb": 2700, "min_disk_mb": 1,
        "engine_factory": lambda: None, "requires_extra": "paddle", "preferred_device": "gpu",
        "gpu_speedup": 4.3,
    }
    return ModelSpec(**{**base, **overrides})


def _caps() -> DeviceCapabilities:
    return DeviceCapabilities(
        ram_total_gb=16, ram_available_gb=8, cpu_physical_cores=8, cpu_logical_cores=16,
        disk_free_gb=100, disk_total_gb=500, gpu_name="NVIDIA GeForce RTX 3060",
        gpu_memory_gb=12.0, os_name="Linux", arch="x86_64",
    )


USABLE = gpu.Support(True)


def _choose(spec=None, **kw):
    args = {"setting": "auto", "supported": USABLE, "gpu_build": True, "free_gb": 10.0}
    return gpu.choose(spec or _spec(), **{**args, **kw})


# --- this computer ----------------------------------------------------------------------


def test_support_needs_the_platform_a_card_a_new_enough_driver_and_a_known_card() -> None:
    assert gpu.support(_gpu(), platform_ok=True).usable
    assert not gpu.support(_gpu(), platform_ok=False).usable

    old_driver = gpu.support(_gpu(cuda_version="12.4", driver_version="550.54"), platform_ok=True)
    assert not old_driver.usable and "12.6" in old_driver.reason and "550.54" in old_driver.reason

    maxwell = gpu.support(_gpu(name="GTX 970", compute_capability="5.2"), platform_ok=True)
    assert not maxwell.usable and "too old" in maxwell.reason

    blackwell = gpu.support(_gpu(name="RTX 5090", compute_capability="12.0"), platform_ok=True)
    assert not blackwell.usable and "RTX 5090" in blackwell.reason

    hopper = gpu.support(_gpu(compute_capability="9.0"), platform_ok=True)
    assert hopper.usable
    # Old drivers don't report these: then the card gets the benefit of the doubt.
    assert gpu.support(_gpu(compute_capability=None, cuda_version=None), platform_ok=True).usable


def test_support_without_a_card(monkeypatch) -> None:
    monkeypatch.setattr(device, "nvidia_gpu", lambda: None)
    result = gpu.support(platform_ok=True)
    assert not result.usable and "NVIDIA" in result.reason


def test_nvidia_smi_is_parsed(monkeypatch) -> None:
    answers = {
        "--query-gpu=name,memory.total,driver_version,compute_cap":
            "NVIDIA GeForce RTX 3060, 12288, 595.91.07, 8.6\n",
        "--query-gpu=memory.free": "10660\n",
    }
    monkeypatch.setattr(device.shutil, "which", lambda _: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(device, "_run", lambda cmd: (
        "| NVIDIA-SMI 595.91.07   Driver Version: 595.91.07   CUDA Version: 13.2 |"
        if len(cmd) == 1 else answers.get(cmd[1])
    ))
    device.nvidia_gpu.cache_clear()
    try:
        assert device.nvidia_gpu() == _gpu()
        assert device.gpu_free_memory_gb() == 10.41
    finally:
        device.nvidia_gpu.cache_clear()


def test_nvidia_smi_without_compute_cap(monkeypatch) -> None:
    def run(cmd):
        if len(cmd) == 1:
            return ""
        return None if "compute_cap" in cmd[1] else "Quadro P2000, 5120, 470.10\n"

    monkeypatch.setattr(device.shutil, "which", lambda _: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(device, "_run", run)
    device.nvidia_gpu.cache_clear()
    try:
        found = device.nvidia_gpu()
        assert (found.name, found.memory_gb, found.driver_version) == ("Quadro P2000", 5.0, "470.10")
        assert found.compute_capability is None and found.cuda_version is None
    finally:
        device.nvidia_gpu.cache_clear()


# --- which models read on the card ------------------------------------------------------


def test_auto_puts_the_models_that_read_best_on_a_card_there() -> None:
    assert _choose().device == "gpu"
    assert _choose(_spec(preferred_device="cpu")).device == "cpu"  # Mobile: quick anyway


def test_settings_force_either_device() -> None:
    assert _choose(_spec(preferred_device="cpu"), setting="gpu").device == "gpu"
    on_cpu = _choose(setting="cpu")
    assert (on_cpu.device, on_cpu.setting, on_cpu.note) == ("cpu", "cpu", None)


def test_engines_without_a_graphics_card_build_stay_on_the_processor() -> None:
    tesseract = _spec(requires_extra=None, engine="Tesseract")
    assert _choose(tesseract, setting="gpu").device == "cpu"
    assert not gpu.gpu_capable(tesseract)


def test_what_keeps_a_model_on_the_processor_is_said() -> None:
    unusable = gpu.Support(False, "No NVIDIA graphics card with its driver installed was found.")
    # Nothing to tell on auto: the computer can't, and the model's note already says so.
    assert _choose(supported=unusable).note is None
    assert _choose(supported=unusable, setting="gpu").note == unusable.reason

    no_build = _choose(gpu_build=False)
    assert no_build.device == "cpu" and "under Device" in no_build.note

    short = _choose(free_gb=2.0)
    assert short.device == "cpu" and "3.1 GB of graphics memory" in short.note

    fell_back = _choose(fallback="Ran out of graphics memory, so it reads on the processor.")
    assert fell_back.device == "cpu" and "Ran out" in fell_back.note

    assert _choose(free_gb=None).device == "gpu"  # unknown free memory doesn't block it


def test_a_models_own_setting_wins_over_the_global_one() -> None:
    config_store.set_device_preference("cpu")
    config_store.set_model_devices({"t": "gpu"})
    assert gpu.setting_for("t") == "gpu"
    assert gpu.setting_for("other") == "cpu"
    config_store.set_model_devices({"t": "auto"})
    assert gpu.setting_for("t") == "cpu"
    assert config_store.get_model_devices() == {}


def test_the_model_info_says_where_and_why() -> None:
    on_card = inference_device(_spec(), _caps(), _choose())
    assert (on_card.runs_on, on_card.gpu_capable, on_card.note) == ("gpu", True, None)

    needs_build = inference_device(_spec(), _caps(), _choose(gpu_build=False))
    assert needs_build.runs_on == "cpu"
    assert "about 4.3× faster" in needs_build.note and "under Device" in needs_build.note

    user_cpu = inference_device(_spec(), _caps(), _choose(setting="cpu"))
    assert user_cpu.setting == "cpu" and user_cpu.note is None


# --- loading, and falling back ----------------------------------------------------------


class _FakeEngine:
    def __init__(self, fail_on_gpu: bool) -> None:
        self.fail_on_gpu = fail_on_gpu
        self.device = "cpu"
        self.loads: list[str] = []

    def use_device(self, device_: str) -> None:
        self.device = device_

    def load(self) -> None:
        self.loads.append(self.device)
        if self.device == "gpu" and self.fail_on_gpu:
            raise RuntimeError("CUDA error: no kernel image is available for execution")


def test_a_card_that_fails_to_load_falls_back_to_the_processor(monkeypatch) -> None:
    monkeypatch.setattr(gpu, "device_for", lambda spec: gpu.Choice("gpu", "auto"))
    engine = _FakeEngine(fail_on_gpu=True)
    assert gpu.load(_spec(), engine) == "cpu"
    assert engine.loads == ["gpu", "cpu"]
    assert "no kernel image" in gpu.fallback_for("t")

    # Shown on the model, and it stays on the processor until the settings change.
    assert _choose(fallback=gpu.fallback_for("t")).device == "cpu"

    engine = _FakeEngine(fail_on_gpu=False)
    assert gpu.load(_spec(), engine) == "gpu"
    assert gpu.fallback_for("t") is None


def test_engines_without_a_device_just_load(monkeypatch) -> None:
    class Plain:
        loaded = False

        def load(self):
            self.loaded = True

    engine = Plain()
    assert gpu.load(_spec(requires_extra=None), engine) == "cpu" and engine.loaded


class _Pipeline:
    def __init__(self, errors: list[Exception | None]) -> None:
        self.errors = errors

    def predict(self, _path):
        error = self.errors.pop(0) if self.errors else None
        if error:
            raise error
        return [{"rec_texts": ["hello"], "rec_scores": [0.9], "rec_boxes": [[0, 0, 5, 5]]}]


def _paddle_on_gpu(monkeypatch, gpu_errors: list) -> PaddleOcrEngine:
    engine = PaddleOcrEngine(model_id="t", det_model_name="d", rec_model_name="r", device="gpu")
    engine._ocr = _Pipeline(gpu_errors)
    monkeypatch.setattr(engine, "load", lambda: setattr(engine, "_ocr", _Pipeline([])))
    return engine


def test_paddle_reads_the_page_again_on_the_processor_when_the_card_fails_at_first(
    monkeypatch,
) -> None:
    engine = _paddle_on_gpu(monkeypatch, [RuntimeError("cuDNN couldn't be loaded")])
    assert engine.run(Image.new("RGB", (40, 40))).text == "hello"
    assert engine.device == "cpu" and "cuDNN" in gpu.fallback_for("t")


def test_paddle_falls_back_when_the_card_runs_out_of_memory(monkeypatch) -> None:
    engine = _paddle_on_gpu(monkeypatch, [None, MemoryError("Out of memory error on GPU 0")])
    image = Image.new("RGB", (40, 40))
    engine.run(image)
    assert engine.run(image).text == "hello"
    assert engine.device == "cpu" and "Ran out of graphics memory" in gpu.fallback_for("t")


def test_paddle_doesnt_hide_other_errors_after_the_first_page(monkeypatch) -> None:
    engine = _paddle_on_gpu(monkeypatch, [None, ValueError("bad image")])
    image = Image.new("RGB", (40, 40))
    engine.run(image)
    with pytest.raises(ValueError):
        engine.run(image)
    assert engine.device == "gpu"


def test_paddle_asks_for_the_card_by_name(monkeypatch) -> None:
    from docbox.backend.engines import paddleocr_engine

    assert paddleocr_engine.paddle_device("gpu") == "gpu:0"
    assert paddleocr_engine.paddle_device("cpu") == "cpu"
    engine = PaddleOcrEngine(model_id="t", det_model_name="d", rec_model_name="r")
    engine._ocr = object()
    engine.use_device("gpu")
    assert engine._ocr is None and engine.device == "gpu"  # rebuilt on the next load


# --- the engines' builds ----------------------------------------------------------------


@pytest.fixture()
def fake_dists(monkeypatch):
    """Installed engines and distributions, as runtime sees them."""
    installed: dict[str, str] = {}
    monkeypatch.setattr(runtime, "_dist_version", lambda name: installed.get(name))
    monkeypatch.setattr(runtime, "installed_extras", lambda: {
        e for e, (_label, marker) in runtime.EXTRAS.items() if marker in installed
    })
    return installed


def test_which_build_is_installed(fake_dists) -> None:
    assert runtime.build_of("paddle") is None
    fake_dists.update(paddleocr="3.7.0", paddlepaddle="3.2.2")
    assert runtime.build_of("paddle") == "cpu"
    fake_dists.pop("paddlepaddle")
    fake_dists["paddlepaddle-gpu"] = "3.2.2"
    assert runtime.build_of("paddle") == "gpu"

    fake_dists.update(easyocr="1.7.2", torch="2.14.1+cpu")
    assert runtime.build_of("easyocr") == "cpu"
    fake_dists["torch"] = "2.14.1+cu126"
    assert runtime.build_of("easyocr") == "gpu"
    assert runtime.synced_extras() == {"paddle-gpu", "easyocr-gpu"}


def test_switching_is_an_exact_sync_that_keeps_the_other_engines(
    monkeypatch, fake_dists,
) -> None:
    fake_dists.update(paddleocr="3.7.0", paddlepaddle="3.2.2", easyocr="1.7.2",
                      torch="2.14.1+cpu")
    ran: list[list[str]] = []

    def sync(cmd, _cb, **_):
        ran.append(cmd)
        fake_dists.pop("paddlepaddle")
        fake_dists["paddlepaddle-gpu"] = "3.2.2"

    monkeypatch.setenv("DOCBOX_RUNTIME_MODE", "dev")
    monkeypatch.setenv("DOCBOX_UV", "uv")
    monkeypatch.setattr(runtime, "gpu_builds_supported", lambda: True)
    monkeypatch.setattr(runtime, "run_streaming", sync)
    monkeypatch.setattr(runtime.sys, "modules", {k: v for k, v in sys.modules.items()
                                                 if k.split(".")[0] not in ("paddle", "paddleocr",
                                                                            "paddlex")})
    runtime.switch_build("paddle", "gpu", lambda *_: None)
    cmd = ran[0]
    assert "--inexact" not in cmd
    assert cmd[cmd.index("sync"):][:2] == ["sync", "--frozen"]
    extras = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--extra"]
    assert extras == ["easyocr", "paddle-gpu"]


def test_only_one_engine_uses_the_card(monkeypatch, fake_dists) -> None:
    fake_dists.update(paddleocr="3.7.0", **{"paddlepaddle-gpu": "3.2.2"}, easyocr="1.7.2",
                      torch="2.14.1+cpu")
    monkeypatch.setattr(runtime, "gpu_builds_supported", lambda: True)
    with pytest.raises(runtime.GpuBuildTaken, match="PaddleOCR"):
        runtime.switch_build("easyocr", "gpu", lambda *_: None)


def test_a_switch_of_a_loaded_engine_waits_for_a_restart(monkeypatch, fake_dists) -> None:
    fake_dists.update(paddleocr="3.7.0", paddlepaddle="3.2.2")
    monkeypatch.setenv("DOCBOX_RUNTIME_MODE", "managed")
    monkeypatch.setattr(runtime, "gpu_builds_supported", lambda: True)
    monkeypatch.setitem(sys.modules, "paddle", object())
    with pytest.raises(runtime.RemovalNeedsRestart, match="next time DocBox starts"):
        runtime.switch_build("paddle", "gpu", lambda *_: None)
    state = runtime.read_state()
    assert state["extras"] == ["paddle-gpu"] and state["resync_pending"] is True
    # The engine stays listed as installed, not as being removed.
    assert runtime.state_engines() == {"paddle"}


def test_no_graphics_card_builds_on_macos(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "gpu_builds_supported", lambda: False)
    with pytest.raises(runtime.EngineInstallError, match="Windows and Linux"):
        runtime.switch_build("paddle", "gpu", lambda *_: None)
    assert not gpu.support(platform_ok=False).usable


def test_download_sizes_are_known_where_the_builds_exist() -> None:
    for extra in runtime.GPU_BUILDS:
        for platform in ("linux", "win32"):
            assert runtime.GPU_DOWNLOAD_MB[(extra, platform)] > 1000


# --- settings and routes ----------------------------------------------------------------


def test_device_settings_round_trip_and_unload_loaded_models(client, monkeypatch) -> None:
    evicted: list = []
    monkeypatch.setattr(engine_cache, "evict_all", lambda ids=None: evicted.append(ids))
    gpu.record_fallback("paddleocr-balanced", "it failed")

    body = client.patch("/api/settings", json={
        "device_preference": "gpu", "model_devices": {"paddleocr-mobile-en": "cpu"},
    }).json()
    assert body["device_preference"] == "gpu"
    assert body["model_devices"] == {"paddleocr-mobile-en": "cpu"}
    assert evicted == [None] and gpu.fallback_for("paddleocr-balanced") is None

    body = client.patch("/api/settings", json={"model_devices": {"paddleocr-mobile-en": "auto"}})
    assert body.json()["model_devices"] == {}
    assert client.patch("/api/settings", json={"model_devices": {"nope": "gpu"}}).status_code == 404
    assert client.patch("/api/settings", json={"device_preference": "tpu"}).status_code == 422


def test_models_list_where_they_read(client, monkeypatch) -> None:
    monkeypatch.setattr(gpu, "support", lambda: gpu.Support(False, "no card"))
    models = {m["id"]: m for m in client.get("/api/models").json()}
    balanced = models["paddleocr-balanced"]["device"]
    assert balanced["gpu_capable"] is True and balanced["runs_on"] == "cpu"
    assert models["tesseract-eng"]["device"]["gpu_capable"] is False


def test_gpu_status_route(client, monkeypatch) -> None:
    monkeypatch.setattr(gpu, "support", lambda: gpu.Support(False, "no card"))
    body = client.get("/api/engines/gpu").json()
    assert body["usable"] is False and body["reason"] == "no card"
    assert body["cuda_required"] == "12.6"
    assert {e["id"] for e in body["engines"]} == {"paddle", "easyocr"}
    for engine in body["engines"]:
        if engine["installed"] != "gpu":
            assert engine["blocked"] == "no card"


def test_switching_build_refuses_up_front(client, monkeypatch) -> None:
    monkeypatch.setattr(gpu, "support", lambda: gpu.Support(False, "no card"))
    monkeypatch.setattr(runtime, "build_of", lambda name: "cpu")
    assert client.post("/api/engines/nope/build", json={"build": "gpu"}).status_code == 404
    refused = client.post("/api/engines/paddle/build", json={"build": "gpu"})
    assert refused.status_code == 400 and "no card" in refused.json()["detail"]
    assert client.get("/api/engines/build/status", params={"job_id": "x"}).status_code == 404


def test_switch_job_reports_a_restart(monkeypatch) -> None:
    monkeypatch.setattr(engines_service, "_check_switch", lambda *_: None)

    def needs_restart(*_):
        raise runtime.RemovalNeedsRestart("PaddleOCR engine is in use; it switches later.")

    monkeypatch.setattr(runtime, "switch_build", needs_restart)
    started = engines_service.start_switch_build("paddle", "gpu", lambda work: work())
    status = engines_service.build_status(started.job_id)
    assert status.state == "done" and "switches later" in status.message
