"""What the benchmark graph and ranked bars read off each leaderboard row: the engine,
the family of sizes a model belongs to, the interval around its accuracy, and an honest
"not measured" where a worker can't see the model's memory."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docbox.backend import platforms
from docbox.backend.api import routes_benchmarks
from docbox.backend.main import create_app
from docbox.backend.platforms import ollama
from docbox.benchmark import metrics, report, store
from docbox.benchmark.runner import BenchConfig
from docbox.benchmark.store import BenchFile, BenchRun, ModelRun, PageResult, References
from docbox.service import benchmarks


def _units(*pairs: tuple[int, int]) -> list[metrics.Score]:
    return [metrics.Score(edits, chars, 0, 1) for edits, chars in pairs]


def test_no_interval_without_spread_to_measure() -> None:
    assert metrics.cer_margin([]) is None
    assert metrics.cer_margin(_units((1, 10))) is None
    assert metrics.cer_margin(_units((0, 0), (0, 0))) is None


def test_interval_from_how_much_pages_disagree() -> None:
    # Same rate on every page: nothing to be unsure about.
    assert metrics.cer_margin(_units((1, 10), (2, 20), (3, 30))) == pytest.approx(0)
    # 0/10 and 2/10: rate 0.1, ratio-estimator SE 0.1, and with one degree of freedom
    # Student's t (12.706) makes the interval far wider than ±1.96 SE would.
    assert metrics.cer_margin(_units((0, 10), (2, 10))) == pytest.approx(12.706 * 0.1)
    # Past 31 units the t value has settled at the normal 1.96.
    many = _units(*[(0, 10), (2, 10)] * 20)
    rate, k = 0.1, 40
    se = (k / (k - 1) * sum((e.char_edits - rate * 10) ** 2 for e in many)) ** 0.5 / 400
    assert metrics.cer_margin(many) == pytest.approx(1.96 * se)


def test_ollama_tags_are_sizes_of_one_model() -> None:
    assert ollama.family_and_variant("qwen2.5vl:7b") == ("Ollama — qwen2.5vl", "7b")
    assert ollama.family_and_variant("llava") == ("Ollama — llava", None)
    assert ollama.family_and_variant("llava:latest") == ("Ollama — llava", None)


def test_describe_needs_no_platform_to_be_running() -> None:
    assert platforms.describe("paddleocr-mobile-en") == ("paddleocr", "PaddleOCR — English", "Mobile")
    assert platforms.describe("paddleocr-accurate-en") == ("paddleocr", "PaddleOCR — English", "Large")
    assert platforms.describe("tesseract-eng") == ("tesseract", None, None)
    assert platforms.describe("ollama:minicpm-v:8b") == ("ollama", "Ollama — minicpm-v", "8b")
    assert platforms.describe("nvidia-nim:some/model") == ("nvidia-nim", None, None)
    assert platforms.describe("gone-model") == ("other", None, None)


def test_rows_carry_engine_family_and_accuracy_interval() -> None:
    files = [BenchFile(id=f"f{i}", path=f"/x/f{i}.png", pages=1, has_reference=True)
             for i in range(4)]
    run = BenchRun(id="r", name="r", created_at=0, files=files, models=[
        ModelRun(model_id="paddleocr-mobile-en", name="PaddleOCR Mobile — English", state="done"),
        ModelRun(model_id="ollama:qwen2.5vl:7b", name="Ollama — qwen2.5vl:7b", state="done",
                 memory_note="Runs inside Ollama, so its memory isn't measured here"),
    ])
    refs = References(whole={f.id: "abcdefghij" for f in files})
    # Mobile reads two files perfectly and gets 2 of 10 characters wrong in the other two;
    # the Ollama model reads every file perfectly.
    results = [PageResult(model_id="paddleocr-mobile-en", file_id=f.id, page=1,
                          text="abcdefghij" if i % 2 else "abcdefghXY", seconds=0.5)
               for i, f in enumerate(files)]
    results += [PageResult(model_id="ollama:qwen2.5vl:7b", file_id=f.id, page=1,
                           text="abcdefghij", seconds=3.0) for f in files]
    rows = {r.model_id: r for r in report.summarize(run, results, refs).leaderboard}

    mobile = rows["paddleocr-mobile-en"]
    assert (mobile.engine, mobile.family, mobile.variant) == ("paddleocr", "PaddleOCR — English", "Mobile")
    assert mobile.accuracy == 0.9 and mobile.scored_units == 4
    assert mobile.accuracy_margin == pytest.approx(metrics.cer_margin(_units(
        (2, 10), (0, 10), (2, 10), (0, 10))), abs=1e-4)

    qwen = rows["ollama:qwen2.5vl:7b"]
    assert (qwen.engine, qwen.family, qwen.variant) == ("ollama", "Ollama — qwen2.5vl", "7b")
    assert qwen.accuracy == 1.0 and qwen.accuracy_margin == 0
    assert qwen.peak_memory_mb is None and "isn't measured" in qwen.memory_note


REMOTE_FAKE = '''
from bench_fakes import FakeEngine
from docbox.backend.core.registry import ModelSpec, registry


class RemoteFake(FakeEngine):
    runs_in_process = False


registry.register(ModelSpec(
    id="fake-remote", name="Fake remote", engine="fake", description="test double",
    languages=["en"], approx_download_mb=1, approx_ram_mb=1, min_disk_mb=1,
    engine_factory=lambda: RemoteFake("good"),
))
'''


def test_a_model_running_in_another_process_has_no_memory_figure(fakes, docs, tmp_path,
                                                                  monkeypatch) -> None:
    (tmp_path / "remote_fake.py").write_text(REMOTE_FAKE)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("DOCBOX_PRELOAD", "bench_fakes,remote_fake")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(tmp_path), os.environ["PYTHONPATH"]]))
    import remote_fake  # noqa: F401 — registers fake-remote here as well as in the worker

    run = benchmarks.run_now(BenchConfig(sources=[docs], models=["fake-good", "fake-remote"]))
    models = {m.model_id: m for m in run.models}
    assert models["fake-good"].peak_memory_mb > 10 and models["fake-good"].memory_note is None
    assert models["fake-remote"].peak_memory_mb is None
    assert models["fake-remote"].memory_note == ("Runs in another process, so its memory "
                                                 "isn't measured here")
    rows = {r.model_id: r for r in run.summary.leaderboard}
    assert rows["fake-remote"].memory_note == models["fake-remote"].memory_note


def test_the_report_opens_by_run_id(fakes, docs, monkeypatch) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(routes_benchmarks, "open_path", opened.append)
    client = TestClient(create_app(), base_url="http://127.0.0.1:8756")
    run = benchmarks.run_now(BenchConfig(sources=[docs], models=["fake-good"]))

    assert client.post(f"/api/benchmarks/{run.id}/report/open").status_code == 204
    assert client.post(f"/api/benchmarks/{run.id}/report/open?target=folder").status_code == 204
    assert opened == [store.run_dir(run.id) / "report.md", store.run_dir(run.id)]

    # Not written yet (or gone), and unknown or malformed ids, are all 404.
    (store.run_dir(run.id) / "report.md").unlink()
    assert client.post(f"/api/benchmarks/{run.id}/report/open").status_code == 404
    assert client.post("/api/benchmarks/20991231-000000-abcdef/report/open").status_code == 404
    assert client.post("/api/benchmarks/..%2F..%2Fsecret/report/open").status_code == 404
    assert len(opened) == 2
