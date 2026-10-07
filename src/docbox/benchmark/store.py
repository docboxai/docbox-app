"""Saved benchmark runs: one folder per run under <data>/benchmarks/<run_id>/.

  run.json         BenchRun: what was asked, state, progress, per-model stats, summary
  references.json  the reference text per file (copied, so the run stays scorable)
  results.jsonl    one PageResult per model per page, appended as they arrive
  report.md        written when the run finishes
  inputs/          files uploaded from the app (CLI and MCP runs reference paths)
  cancel           present when someone asked the run to stop

Any DocBox process may read a run; only the process running it writes run.json and
results.jsonl, so run.json is replaced atomically and needs no lock.
"""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path
from typing import Literal

import psutil
from pydantic import BaseModel

from docbox.backend.core.paths import get_data_dir
from docbox.backend.schemas import OcrLine
from docbox.service.errors import NotFound

RunState = Literal["queued", "running", "done", "error", "cancelled", "interrupted"]
ModelRunState = Literal["pending", "installing", "running", "done", "error", "skipped"]
_UNFINISHED: tuple[RunState, ...] = ("queued", "running")


class BenchFile(BaseModel):
    id: str
    path: str
    pages: int
    has_reference: bool


class ModelRun(BaseModel):
    model_id: str
    name: str
    state: ModelRunState = "pending"
    error: str | None = None
    load_seconds: float | None = None
    peak_memory_mb: float | None = None


class LeaderboardRow(BaseModel):
    model_id: str
    name: str
    rank: int | None = None
    pages_read: int
    pages_failed: int
    load_seconds: float | None = None
    seconds_per_page: float | None = None
    median_seconds_per_page: float | None = None
    peak_memory_mb: float | None = None
    mean_confidence: float | None = None
    # Only when some reference text was given; accuracy is 1 - CER.
    cer: float | None = None
    wer: float | None = None
    accuracy: float | None = None
    scored_chars: int = 0


class BenchSummary(BaseModel):
    ranked_by: Literal["cer", "speed"]
    leaderboard: list[LeaderboardRow]
    best_model_id: str | None = None


class BenchRun(BaseModel):
    id: str
    name: str
    created_at: float
    finished_at: float | None = None
    state: RunState = "queued"
    error: str | None = None
    ignore_case: bool = False
    # How it was started: "cli" | "mcp" | "app"
    source: str = "cli"
    files: list[BenchFile]
    models: list[ModelRun]
    pages_total: int = 0
    # Pages read so far, over every model (pages_total * models when done).
    pages_done: int = 0
    current_model_id: str | None = None
    pid: int | None = None
    summary: BenchSummary | None = None

    @property
    def has_reference(self) -> bool:
        return any(f.has_reference for f in self.files)


class PageResult(BaseModel):
    model_id: str
    file_id: str
    page: int
    text: str = ""
    lines: list[OcrLine] = []
    seconds: float | None = None
    error: str | None = None


class References(BaseModel):
    # file id -> reference for the whole document / for single pages ("3": text)
    whole: dict[str, str] = {}
    pages: dict[str, dict[str, str]] = {}


def root() -> Path:
    d = get_data_dir() / "benchmarks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_id() -> str:
    # Sortable by time, short enough to type: 20261007-142233-1a2b3c
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def run_dir(run_id: str) -> Path:
    # Ids are ours (new_id); refuse anything that could name another path.
    if not run_id or any(c not in "0123456789abcdef-" for c in run_id):
        raise NotFound(f"Unknown benchmark: {run_id}")
    return root() / run_id


def save(run: BenchRun) -> None:
    d = run_dir(run.id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "run.json.tmp"
    tmp.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(d / "run.json")


def _alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def load(run_id: str) -> BenchRun:
    path = run_dir(run_id) / "run.json"
    try:
        run = BenchRun.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise NotFound(f"Unknown benchmark: {run_id}") from None
    if run.state in _UNFINISHED and run.pid is not None and not _alive(run.pid):
        # The process running it died (closed window, killed agent): it won't finish.
        run.state = "interrupted"
        run.error = "DocBox stopped before this benchmark finished"
        run.current_model_id = None
        save(run)
    return run


def list_runs() -> list[BenchRun]:
    runs = []
    for d in root().iterdir():
        if (d / "run.json").is_file():
            try:
                runs.append(load(d.name))
            except NotFound:
                continue
    return sorted(runs, key=lambda r: r.created_at, reverse=True)


def delete(run_id: str) -> None:
    d = run_dir(run_id)
    if not (d / "run.json").exists():
        raise NotFound(f"Unknown benchmark: {run_id}")
    shutil.rmtree(d)


def save_references(run_id: str, refs: References) -> None:
    (run_dir(run_id) / "references.json").write_text(refs.model_dump_json(), encoding="utf-8")


def load_references(run_id: str) -> References:
    try:
        return References.model_validate_json(
            (run_dir(run_id) / "references.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return References()


def append_result(run_id: str, result: PageResult) -> None:
    with (run_dir(run_id) / "results.jsonl").open("a", encoding="utf-8") as f:
        f.write(result.model_dump_json() + "\n")


def load_results(run_id: str) -> list[PageResult]:
    path = run_dir(run_id) / "results.jsonl"
    if not path.exists():
        return []
    results = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                results.append(PageResult.model_validate_json(line))
            except ValueError:
                continue  # a line cut short by a crash
    return results


def request_cancel(run_id: str) -> None:
    run = load(run_id)
    if run.state in _UNFINISHED:
        (run_dir(run_id) / "cancel").touch()


def cancel_requested(run_id: str) -> bool:
    return (run_dir(run_id) / "cancel").exists()


def write_report(run_id: str, markdown: str) -> Path:
    path = run_dir(run_id) / "report.md"
    path.write_text(markdown, encoding="utf-8", newline="\n")
    return path


def inputs_dir(run_id: str) -> Path:
    d = run_dir(run_id) / "inputs"
    d.mkdir(parents=True, exist_ok=True)
    return d
