"""Benchmarks as every front end sees them: start one, follow it, read the results."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from docbox.benchmark import report, runner, store
from docbox.benchmark.report import PageView
from docbox.benchmark.runner import BenchConfig
from docbox.benchmark.store import BenchRun
from docbox.service.errors import Conflict, Invalid

ReportFormat = Literal["md", "json", "csv"]

__all__ = [
    "BenchConfig", "cancel", "delete", "get", "list_runs", "page", "render_report",
    "run_now", "start",
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
