"""Benchmarks: datasets and references, scoring, the runner with real worker processes
(fake engines), saved runs, reports and the `docbox bench` commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from docbox.benchmark import dataset, metrics, store
from docbox.benchmark.runner import BenchConfig
from docbox.cli.main import main
from docbox.service import benchmarks
from docbox.service.errors import Conflict, Invalid, NotFound

# --- metrics ----------------------------------------------------------------------------


def test_cer_and_wer_against_hand_counts() -> None:
    assert metrics.cer("Total due $1,2B4.00", "Total due $1,284.00") == pytest.approx(1 / 19)
    assert metrics.wer("Total due $1,2B4.00", "Total due $1,284.00") == pytest.approx(1 / 3)
    assert metrics.cer("abc", "abc") == 0.0


def test_layout_and_unicode_forms_dont_count() -> None:
    assert metrics.cer("Total  due\n\n$5", "Total due $5\n") == 0.0
    assert metrics.cer("ﬁle １２", "file 12") == 0.0  # ligature, full-width digits
    assert metrics.cer("TOTAL", "total") == 1.0
    assert metrics.cer("TOTAL", "total", ignore_case=True) == 0.0


def test_empty_reference() -> None:
    assert metrics.cer("", "") == 0.0
    assert metrics.cer("x", "") == 1.0


def test_scores_add_up_by_length() -> None:
    total = metrics.score("ab", "ab") + metrics.score("x", "yz")
    assert total.cer == pytest.approx(2 / 4)


# --- datasets ---------------------------------------------------------------------------


def test_sidecar_references(docs: Path) -> None:
    data = dataset.resolve([docs])
    by_id = {i.id: i for i in data.items}
    assert set(by_id) == {"invoice.png", "report.pdf", "scan.png"}
    assert by_id["invoice.png"].reference.startswith("Total due")
    assert by_id["report.pdf"].page_references == {2: "Northwind Supply Co.\nPage two"}
    assert not by_id["scan.png"].has_reference
    assert data.name == "docs"


def test_same_file_names_in_subfolders_get_distinct_ids(docs: Path) -> None:
    (docs / "march").mkdir()
    (docs / "invoice.png").rename(docs / "march" / "invoice.png")
    (docs / "april").mkdir()
    (docs / "scan.png").rename(docs / "april" / "invoice.png")
    ids = {i.id for i in dataset.resolve([docs], recursive=True).items}
    assert {"march/invoice.png", "april/invoice.png"} <= ids
    assert "march/invoice.png" not in {i.id for i in dataset.resolve([docs]).items}


def test_manifest_json_and_jsonl(docs: Path) -> None:
    (docs / "ref.txt").write_text("from a file")
    manifest = docs / "set.json"
    manifest.write_text(json.dumps({"name": "Invoices", "items": [
        {"file": "invoice.png", "gt_file": "ref.txt"},
        {"file": "scan.png", "gt": "inline"},
        {"file": "report.pdf", "pages": [{"page": 1, "gt": "p1"}]},
    ]}))
    data = dataset.resolve([manifest])
    assert data.name == "Invoices"
    refs = {i.id: (i.reference, i.page_references) for i in data.items}
    assert refs == {"invoice.png": ("from a file", {}), "scan.png": ("inline", {}),
                    "report.pdf": (None, {1: "p1"})}

    lines = docs / "set.jsonl"
    lines.write_text('{"file": "scan.png", "gt": "x"}\n\n{"file": "invoice.png"}\n')
    assert [i.id for i in dataset.resolve([lines]).items] == ["scan.png", "invoice.png"]


def test_manifest_errors(docs: Path) -> None:
    bad = docs / "bad.json"
    bad.write_text('{"items": [{"file": "missing.png"}]}')
    with pytest.raises(NotFound, match="missing.png"):
        dataset.resolve([bad])
    bad.write_text("{not json")
    with pytest.raises(Invalid):
        dataset.resolve([bad])


def test_nothing_to_read(tmp_path: Path) -> None:
    with pytest.raises(Invalid):
        dataset.resolve([tmp_path])
    with pytest.raises(NotFound):
        dataset.resolve([tmp_path / "nope"])


# --- running ----------------------------------------------------------------------------


def _run(docs: Path, models: list[str], **kw):
    return benchmarks.run_now(BenchConfig(sources=[docs], models=models, **kw))


def test_two_models_ranked_by_accuracy(fakes, docs) -> None:
    run = _run(docs, ["fake-sloppy", "fake-good"])
    assert run.state == "done"
    assert run.pages_total == 4 and run.pages_done == 8
    board = run.summary.leaderboard
    assert run.summary.ranked_by == "cer"
    assert [r.model_id for r in board] == ["fake-good", "fake-sloppy"]
    good, sloppy = board
    assert good.accuracy == 1.0 and good.rank == 1
    assert 0 < sloppy.cer < 0.2 and sloppy.wer > 0
    # Scored: invoice.png as a whole + report.pdf page 2 (page 1 has no reference).
    assert good.scored_chars == len(metrics.normalize(fakes.TEXTS[1])) + len(
        metrics.normalize(fakes.TEXTS[2]))
    assert good.pages_read == 4 and good.mean_confidence == pytest.approx(0.95)
    assert good.peak_memory_mb > 10 and good.load_seconds is not None
    assert run.summary.best_model_id == "fake-good"

    folder = store.run_dir(run.id)
    assert len(store.load_results(run.id)) == 8
    assert "| 1 | Fake good" in (folder / "report.md").read_text()


def test_without_references_ranked_by_speed(fakes, docs) -> None:
    for gt in docs.glob("*.gt.txt"):
        gt.unlink()
    run = _run(docs, ["fake-good"])
    assert run.summary.ranked_by == "speed"
    assert run.summary.leaderboard[0].cer is None


def test_a_crashing_model_fails_its_pages_and_the_run_goes_on(fakes, docs) -> None:
    run = _run(docs, ["fake-crash", "fake-good"])
    crash = next(m for m in run.models if m.model_id == "fake-crash")
    assert crash.state == "error" and "exit code 3" in crash.error
    row = {r.model_id: r for r in run.summary.leaderboard}
    assert row["fake-crash"].pages_failed == 4 and row["fake-crash"].rank is None
    assert row["fake-good"].pages_read == 4
    assert run.pages_done == 8 and run.state == "done"


def test_a_hanging_model_times_out(fakes, docs) -> None:
    started = time.monotonic()
    run = _run(docs, ["fake-hang"], page_timeout=1.5)
    assert time.monotonic() - started < 30
    assert "Timed out" in run.models[0].error
    assert run.summary.leaderboard[0].pages_failed == 4


def test_a_model_that_cant_load(fakes, docs) -> None:
    run = _run(docs, ["fake-brokenload"])
    assert run.models[0].state == "error"
    assert "weights are corrupt" in run.models[0].error


def test_library_output_on_stdout_doesnt_break_the_worker(fakes, docs) -> None:
    run = _run(docs, ["fake-noisy"])
    assert run.summary.leaderboard[0].pages_read == 4


def test_models_not_installed_are_skipped_or_installed(fakes, docs) -> None:
    run = _run(docs, ["fake-notinstalled", "fake-good"])
    skipped = run.models[0]
    assert skipped.state == "skipped" and "install" in skipped.error

    run = _run(docs, ["fake-notinstalled"], install_missing=True)
    assert run.models[0].state == "done"
    assert run.summary.leaderboard[0].accuracy == 1.0


def test_default_is_every_ready_model(fakes, docs, monkeypatch) -> None:
    from docbox.service import models as models_service

    ready = [m for m in models_service.list_models()
             if m.id in ("fake-good", "fake-sloppy")]
    monkeypatch.setattr(models_service, "list_models", lambda: ready)
    run = benchmarks.run_now(BenchConfig(sources=[docs / "scan.png"]))
    assert [m.model_id for m in run.models] == ["fake-good", "fake-sloppy"]


def test_unknown_or_blocked_models_are_refused_up_front(fakes, docs) -> None:
    with pytest.raises(NotFound):
        _run(docs, ["no-such-model"])
    with pytest.raises(Conflict, match="cloud"):
        _run(docs, ["nvidia-nim:some/model"])


def test_background_run_can_be_cancelled(fakes, docs) -> None:
    run = benchmarks.start(BenchConfig(sources=[docs], models=["fake-hang", "fake-good"]))
    deadline = time.monotonic() + 30
    while benchmarks.get(run.id).current_model_id != "fake-hang":
        assert time.monotonic() < deadline
        time.sleep(0.05)
    with pytest.raises(Conflict):
        benchmarks.delete(run.id)  # still running
    benchmarks.cancel(run.id)
    while benchmarks.get(run.id).state == "running":
        assert time.monotonic() < deadline
        time.sleep(0.05)
    done = benchmarks.get(run.id)
    assert done.state == "cancelled"
    assert done.models[1].state == "pending"  # never started
    benchmarks.delete(run.id)
    with pytest.raises(NotFound):
        benchmarks.get(run.id)


def test_a_run_whose_process_died_is_interrupted(fakes, docs) -> None:
    from docbox.benchmark import runner

    run = runner.create(BenchConfig(sources=[docs], models=["fake-good"]))
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    run.state, run.pid = "running", dead.pid
    store.save(run)
    assert store.load(run.id).state == "interrupted"


def test_run_ids_cant_name_other_paths(data_dir) -> None:
    for bad in ("../x", "a/b", "", "..", "C:\\x"):
        with pytest.raises(NotFound):
            store.run_dir(bad)


# --- one page, every model --------------------------------------------------------------


def test_page_view_marks_slips_against_the_reference(fakes, docs) -> None:
    run = _run(docs, ["fake-good", "fake-sloppy"])
    view = benchmarks.page(run.id, "invoice.png", 1)
    assert view.reference_kind == "reference"
    reads = {r.model_id: r for r in view.reads}
    assert reads["fake-good"].slips == 0
    sloppy = reads["fake-sloppy"]
    assert sloppy.slips == 2
    assert [(s.reference, s.text) for s in sloppy.diff if s.op != "equal"] == [
        ("8", "B"), ("0", "O")]
    assert "".join(s.text for s in sloppy.diff) == "Total due $1,2B4.00\nRef INV-O312"


def test_page_view_without_reference_can_compare_against_a_model(fakes, docs) -> None:
    run = _run(docs, ["fake-good", "fake-sloppy"])
    view = benchmarks.page(run.id, "report.pdf", 1)  # page 1 has no reference
    assert view.reference_kind == "none" and all(r.slips is None for r in view.reads)
    view = benchmarks.page(run.id, "report.pdf", 1, against="fake-good")
    assert view.reference_kind == "model"
    assert {r.model_id: r.slips for r in view.reads} == {"fake-good": 0, "fake-sloppy": 2}
    with pytest.raises(NotFound):
        benchmarks.page(run.id, "report.pdf", 3)
    with pytest.raises(NotFound):
        benchmarks.page(run.id, "nope.pdf", 1)


# --- reports and the CLI ----------------------------------------------------------------


def test_reports(fakes, docs) -> None:
    run = _run(docs, ["fake-good", "fake-sloppy"])
    csv_text = benchmarks.render_report(run.id, "csv")
    assert csv_text.splitlines()[0].startswith("model_id,name,rank")
    assert len(csv_text.splitlines()) == 3
    assert json.loads(benchmarks.render_report(run.id, "json"))["id"] == run.id
    assert benchmarks.render_report(run.id, "md").startswith("# docs")


def test_cli_bench_commands(fakes, docs, capsys) -> None:
    assert main(["--json", "bench", "run", str(docs), "-m", "fake-good,fake-sloppy",
                 "--name", "Invoices"]) == 0
    run = json.loads(capsys.readouterr().out)
    assert run["name"] == "Invoices" and run["summary"]["best_model_id"] == "fake-good"

    assert main(["--json", "bench", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["id"] == run["id"] and listed[0]["best_model_id"] == "fake-good"

    assert main(["bench", "show", run["id"]]) == 0
    assert "fake-sloppy" in capsys.readouterr().out

    assert main(["--json", "bench", "page", run["id"], "invoice.png"]) == 0
    assert len(json.loads(capsys.readouterr().out)["reads"]) == 2

    assert main(["bench", "report", run["id"], "-f", "csv"]) == 0
    assert capsys.readouterr().out.startswith("model_id,")

    assert main(["--json", "bench", "cancel", run["id"]]) == 1  # already done
    capsys.readouterr()
    assert main(["--json", "bench", "delete", run["id"], "--yes"]) == 0
    assert main(["--json", "bench", "show", run["id"]]) == 1


def test_worker_events_are_clean_json(fakes, docs) -> None:
    """The worker protocol itself, as another program would see it."""
    job = {"model_id": "fake-noisy",
           "files": [{"id": "invoice.png", "path": str(docs / "invoice.png")}]}
    proc = subprocess.run([sys.executable, "-m", "docbox.benchmark.worker"],
                          input=json.dumps(job), capture_output=True, text=True,
                          env=os.environ.copy(), timeout=60, check=False)
    events = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [e["event"] for e in events] == ["loaded", "page", "done"]
    assert "library chatter" in proc.stderr
