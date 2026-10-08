"""The model stays loaded from one read to the next (core/engine_cache.py): loaded once,
replaced by the next model, let go when idle or when its files are removed, and shared by
concurrent single-page requests one at a time."""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from docbox.backend.core import engine_cache
from docbox.backend.core.registry import ModelSpec, registry
from docbox.service import models as models_service
from tests.backend.reading_fakes import CountingEngine, Stats, png, read, register


@pytest.fixture(autouse=True)
def _no_warm_engines():
    engine_cache.evict_all()
    yield
    engine_cache.evict_all()


@pytest.fixture()
def two_models(data_dir):
    a = register("test-count-a")
    b = register("test-count-b")
    yield a, b
    for spec, _ in (a, b):
        registry._models.pop(spec.id, None)


# --- the model stays loaded ------------------------------------------------------------


def test_a_model_is_loaded_once_for_many_reads(two_models) -> None:
    (a, stats), _ = two_models
    for n in range(3):
        assert read(a, png(), f"scan{n}.png").state == "done"
    assert (stats.loads, stats.runs) == (1, 3)
    assert engine_cache.loaded_model_ids() == ["test-count-a"]


def test_another_model_takes_the_place_of_the_last_one(two_models) -> None:
    (a, stats_a), (b, stats_b) = two_models
    read(a, png())
    read(b, png())
    assert engine_cache.loaded_model_ids() == ["test-count-b"]
    read(a, png())
    assert stats_a.loads == 2 and stats_b.loads == 1


def _wait_until_let_go() -> None:
    deadline = time.monotonic() + 5
    while engine_cache.loaded_model_ids() and time.monotonic() < deadline:
        time.sleep(0.02)


def test_an_idle_model_is_let_go(two_models, monkeypatch) -> None:
    (a, stats), _ = two_models
    monkeypatch.setenv("DOCBOX_ENGINE_IDLE_S", "0.05")
    read(a, png())
    _wait_until_let_go()
    assert engine_cache.loaded_model_ids() == []
    read(a, png())
    assert stats.loads == 2


def test_an_idle_model_is_let_go_whatever_the_clock_says(two_models, monkeypatch) -> None:
    # The idle timer waits in real time. A clock that reads less than that (Windows' on
    # CPython 3.12 ticks every 15.6 ms; this one runs at half speed) mustn't keep the
    # model loaded.
    (a, _), _ = two_models
    monkeypatch.setenv("DOCBOX_ENGINE_IDLE_S", "0.05")
    real, start = time.monotonic, time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: start + (real() - start) / 2)
    read(a, png())
    _wait_until_let_go()
    assert engine_cache.loaded_model_ids() == []


def test_an_idle_model_is_let_go_after_a_read_slow_to_finish(two_models, monkeypatch) -> None:
    # The read that sets the idle timer can be held up past it (a busy computer). The
    # timer mustn't find that read still holding the engine and give up for good.
    (a, _), _ = two_models
    monkeypatch.setenv("DOCBOX_ENGINE_IDLE_S", "0.05")
    schedule = engine_cache._schedule_idle_unload

    def schedule_then_stall(entry) -> None:
        schedule(entry)
        time.sleep(0.2)

    monkeypatch.setattr(engine_cache, "_schedule_idle_unload", schedule_then_stall)
    read(a, png())
    _wait_until_let_go()
    assert engine_cache.loaded_model_ids() == []


def test_idle_unloading_can_be_turned_off(two_models, monkeypatch) -> None:
    (a, _), _ = two_models
    monkeypatch.setenv("DOCBOX_ENGINE_IDLE_S", "0")
    read(a, png())
    time.sleep(0.1)
    assert engine_cache.loaded_model_ids() == ["test-count-a"]


def test_removing_a_model_waits_for_the_read_using_it(two_models) -> None:
    (a, stats), _ = two_models
    stats.gate = threading.Event()
    reading = threading.Thread(target=read, args=(a, png()))
    reading.start()
    assert stats.running.wait(5)

    removed = threading.Event()

    def remove() -> None:
        models_service.remove_model("test-count-a")
        removed.set()

    remover = threading.Thread(target=remove)
    remover.start()
    time.sleep(0.2)
    assert not removed.is_set() and stats.deletes == 0  # the read is still using it

    stats.gate.set()
    reading.join(5)
    remover.join(5)
    assert removed.is_set() and stats.deletes == 1
    assert engine_cache.loaded_model_ids() == []


def test_a_model_whose_files_are_gone_fails_clearly_and_isnt_kept(two_models) -> None:
    (a, stats), _ = two_models
    read(a, png())
    stats.downloaded = False  # removed by another DocBox process
    detail = read(a, png())
    assert detail.state == "error" and "is not downloaded yet" in detail.error
    assert engine_cache.loaded_model_ids() == []


def test_an_engine_that_fails_to_load_isnt_kept(two_models) -> None:
    (a, stats), _ = two_models
    stats.fail_load = True
    with pytest.raises(RuntimeError), engine_cache.loaded(a):
        pass
    assert engine_cache.loaded_model_ids() == []
    stats.fail_load = False
    assert read(a, png()).state == "done"
    assert stats.loads == 2


def test_a_model_registered_again_gets_its_own_engine(two_models) -> None:
    (a, old), _ = two_models
    read(a, png())
    spec, new = register("test-count-a")  # same id, new factory (a plugin reloaded)
    read(spec, png())
    assert (old.loads, new.loads) == (1, 1)


def test_concurrent_single_page_requests_take_turns(client: TestClient, two_models) -> None:
    (_, stats), _ = two_models
    stats.run_delay = 0.05
    codes: list[int] = []

    def post() -> None:
        resp = client.post("/api/ocr/run", files={"file": ("a.png", png(), "image/png")},
                           data={"model_id": "test-count-a"})
        codes.append(resp.status_code)

    threads = [threading.Thread(target=post) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert codes == [200] * 4
    assert stats.loads == 1 and stats.runs == 4 and stats.max_active == 1


def test_single_page_request_for_a_removed_model_is_409(client: TestClient, two_models) -> None:
    (_, stats), _ = two_models
    stats.downloaded = False
    resp = client.post("/api/ocr/run", files={"file": ("a.png", png(), "image/png")},
                       data={"model_id": "test-count-a"})
    assert resp.status_code == 409 and "not downloaded" in resp.json()["detail"]


class _ElsewhereEngine(CountingEngine):
    """Like Ollama's: the model lives in another program, so there's nothing to keep warm."""

    runs_in_process = False


def test_a_model_running_elsewhere_leaves_the_warm_one_loaded(two_models) -> None:
    (a, stats_a), _ = two_models
    stats = Stats()
    elsewhere = ModelSpec(
        id="test-elsewhere", name="Elsewhere", engine="fake", description="test double",
        languages=["en"], approx_download_mb=1, approx_ram_mb=1, min_disk_mb=1,
        engine_factory=lambda: _ElsewhereEngine(stats),
    )
    registry.register(elsewhere)
    try:
        read(a, png())
        assert read(elsewhere, png()).state == "done"
        read(a, png())
        assert stats_a.loads == 1  # still warm after the other model's read
        assert engine_cache.loaded_model_ids() == ["test-count-a"]
        assert (stats.loads, stats.runs) == (1, 1)
    finally:
        registry._models.pop(elsewhere.id, None)


def test_a_warm_easyocr_model_is_checked_without_building_a_second_reader(
        data_dir, monkeypatch) -> None:
    """The cache checks the model's files on every use; for EasyOCR that used to mean
    building a whole second Reader beside the loaded one."""
    from docbox.backend.engines import easyocr_engine

    engine = easyocr_engine.EasyOcrEngine(model_id="easyocr-test", langs=["en"])
    engine._reader = object()  # loaded
    monkeypatch.setattr(engine, "_try_build_reader",
                        lambda **_: pytest.fail("built a second Reader"))
    weights = easyocr_engine._cache_dir() / "english_g2.pth"
    weights.write_bytes(b"")
    assert engine.is_downloaded()
    weights.unlink()  # another process removed the model
    assert not engine.is_downloaded()
