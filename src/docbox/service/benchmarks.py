"""Benchmarks as every front end sees them: start one, follow it, read the results."""

from __future__ import annotations

import mimetypes
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from docbox.backend.core.pages import PageError, load_page
from docbox.benchmark import report, runner, store
from docbox.benchmark.report import PageView
from docbox.benchmark.runner import BenchConfig
from docbox.benchmark.store import BenchRun
from docbox.service.errors import Conflict, Invalid, NotFound

ReportFormat = Literal["md", "json", "csv"]

__all__ = [
    "BenchConfig", "cancel", "delete", "get", "list_runs", "page", "page_image",
    "render_report", "rerun", "run_now", "start",
]


def start(config: BenchConfig) -> BenchRun:
    """Check and queue a benchmark, then run it on a background thread; returns at once."""
    return runner.start_in_background(config)


def run_now(config: BenchConfig, on_progress: Callable[[BenchRun], None] | None = None) -> BenchRun:
    """Check, then run a benchmark to the end on the calling thread."""
    run = runner.create(config)
    return runner.execute(
        run.id, install_missing=config.install_missing, page_timeout=config.page_timeout,
        load_timeout=config.load_timeout, on_progress=on_progress,
    )


def rerun(run_id: str, source: str = "app") -> BenchRun:
    """Run a finished benchmark again (same files, references and models) in the background."""
    run = store.load(run_id)
    if run.state in ("queued", "running"):
        raise Conflict("This benchmark is still running")
    return runner.rerun(run_id, source)


def page_image(run_id: str, file_id: str, page_no: int):
    """One page of a benchmarked file as an image, for showing next to the readings.
    Only files the run recorded: the caller names a file id, never a path."""
    run = store.load(run_id)
    file = next((f for f in run.files if f.id == file_id), None)
    if file is None:
        raise NotFound(f"No file {file_id!r} in this benchmark")
    path = Path(file.path)
    try:
        return load_page(path.read_bytes(), mimetypes.guess_type(path.name)[0], page_no - 1)
    except FileNotFoundError:
        raise NotFound("The file was moved or deleted") from None
    except PageError as exc:
        raise NotFound(str(exc)) from None


def list_runs() -> list[BenchRun]:
    return store.list_runs()


def get(run_id: str) -> BenchRun:
    """The run, with a live leaderboard while it's still going."""
    run = store.load(run_id)
    if run.summary is None and run.state in ("running", "queued"):
        run.summary = report.summarize(run, store.load_results(run_id),
                                       store.load_references(run_id))
    return run


def page(run_id: str, file_id: str, page_no: int, against: str | None = None) -> PageView:
    run = store.load(run_id)
    return report.page_view(run, store.load_results(run_id), store.load_references(run_id),
                            file_id, page_no, against)


def render_report(run_id: str, fmt: ReportFormat = "md") -> str:
    run = get(run_id)
    if fmt == "md":
        return report.to_markdown(run)
    if fmt == "csv":
        return report.to_csv(run)
    if fmt == "json":
        return run.model_dump_json(indent=2)
    raise Invalid(f"Unknown report format: {fmt}")


def report_path(run_id: str) -> Path:
    """The saved Markdown report: written when the benchmark ends, not while it runs."""
    store.load(run_id)  # NotFound for an unknown run
    path = store.run_dir(run_id) / "report.md"
    if not path.is_file():
        raise NotFound("This benchmark has no report yet: it's written when the run ends")
    return path


def cancel(run_id: str) -> BenchRun:
    run = store.load(run_id)
    if run.state not in ("queued", "running"):
        raise Conflict(f"This benchmark has already ended ({run.state})")
    store.request_cancel(run_id)
    return run


def delete(run_id: str) -> None:
    run = store.load(run_id)
    if run.state in ("queued", "running"):
        raise Conflict("This benchmark is still running; cancel it first")
    store.delete(run_id)
