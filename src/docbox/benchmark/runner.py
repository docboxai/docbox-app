"""A benchmark run: check the files and models, then let each model read every page in
its own worker process (worker.py), one model after another, saving results as they come.

    run = runner.create(BenchConfig(sources=["scans/"], models=["paddleocr-mobile-en"]))
    runner.execute(run.id)              # blocks; the CLI does this
    runner.start_in_background(config)  # returns at once; the MCP server and the app

Models run one at a time because OCR is CPU- and memory-heavy: two at once would make
both slower and the speed and memory numbers meaningless.
"""

from __future__ import annotations

import contextlib
import json
import mimetypes
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import psutil

import docbox.backend.models_catalog  # noqa: F401 — importing it fills the registry
from docbox.backend.core.pages import PageError, count_pages
from docbox.backend.core.paths import get_data_dir
from docbox.benchmark import dataset as datasets
from docbox.benchmark import report, store
from docbox.benchmark.store import BenchFile, BenchRun, ModelRun, PageResult, References
from docbox.service import models as models_service
from docbox.service.errors import Invalid, ServiceError

# Waiting this long for the next page means the model is stuck: stop it, move on.
PAGE_TIMEOUT_S = 300.0
# Loading can include compiling or reading GBs of weights from a slow disk.
LOAD_TIMEOUT_S = 900.0
_MEMORY_SAMPLE_S = 0.1

Progress = Callable[[BenchRun], None]


@dataclass
class BenchConfig:
    sources: list[str | Path]
    # Model ids; empty means every model that's ready to read now.
    models: list[str] = field(default_factory=list)
    name: str | None = None
    recursive: bool = False
    install_missing: bool = False
    ignore_case: bool = False
    source: str = "cli"
    # Set when the caller already made the run's folder (the app saves uploads into it).
    run_id: str | None = None
    page_timeout: float = PAGE_TIMEOUT_S
    load_timeout: float = LOAD_TIMEOUT_S


def _pick_models(ids: list[str]) -> list[ModelRun]:
    if ids:
        picked = []
        for model_id in dict.fromkeys(ids):  # keep order, drop repeats
            spec = models_service.resolve(model_id)  # NotFound / Blocked (cloud off)
            picked.append(ModelRun(model_id=spec.id, name=spec.name))
        return picked
    ready = [m for m in models_service.list_models() if m.status == "ready"]
    if not ready:
        raise Invalid("No model is ready to read yet; install one first (docbox models install)")
    return [ModelRun(model_id=m.id, name=m.name) for m in ready]


def create(config: BenchConfig) -> BenchRun:
    """Check everything that can be checked up front and save the run as queued."""
    data = datasets.resolve(config.sources, recursive=config.recursive)
    models = _pick_models(config.models)

    files: list[BenchFile] = []
    refs = References()
    for item in data.items:
        try:
            pages = count_pages(item.path.read_bytes(), mimetypes.guess_type(item.path.name)[0],
                                item.path.name)
        except (OSError, PageError) as exc:
            raise Invalid(f"Can't read {item.path}: {exc}") from None
        files.append(BenchFile(id=item.id, path=str(item.path.resolve()), pages=pages,
                               has_reference=item.has_reference))
        if item.page_references:
            refs.pages[item.id] = {str(p): t for p, t in item.page_references.items()}
        elif item.reference is not None:
            refs.whole[item.id] = item.reference

    pages_total = sum(f.pages for f in files)
    run = BenchRun(
        id=config.run_id or store.new_id(),
        name=config.name or data.name or f"{len(files)} file{'s' * (len(files) != 1)}",
        created_at=time.time(),
        ignore_case=config.ignore_case,
        source=config.source,
        files=files,
        models=models,
        pages_total=pages_total,
    )
    store.save(run)
    store.save_references(run.id, refs)
    return run


def start_in_background(config: BenchConfig) -> BenchRun:
    return _launch(create(config), config)


def rerun(run_id: str, source: str) -> BenchRun:
    """The same files, references and models again, as a new run."""
    old = store.load(run_id)
    missing = [f.path for f in old.files if not Path(f.path).is_file()]
    if missing:
        raise Invalid(f"Some files are gone: {', '.join(missing[:3])}")
    new_id = store.new_id()
    old_dir = store.run_dir(old.id).resolve()
    files = []
    for f in old.files:
        path = Path(f.path)
        if path.resolve().is_relative_to(old_dir):
            # Uploaded with the old run: copy it, so deleting that run leaves this one whole.
            target = store.inputs_dir(new_id) / path.resolve().relative_to(old_dir / "inputs")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            path = target
        files.append(f.model_copy(update={"path": str(path)}))
    run = BenchRun(
        id=new_id, name=old.name, created_at=time.time(),
        ignore_case=old.ignore_case, source=source, files=files,
        models=[ModelRun(model_id=m.model_id, name=m.name) for m in old.models],
        pages_total=old.pages_total,
    )
    store.save(run)
    store.save_references(run.id, store.load_references(old.id))
    return _launch(run, BenchConfig(sources=[]))


def _launch(run: BenchRun, config: BenchConfig) -> BenchRun:
    run.pid = os.getpid()  # so a reader in another process can tell it's alive
    store.save(run)
    threading.Thread(
        target=execute, args=(run.id,), kwargs={"install_missing": config.install_missing,
                                                "page_timeout": config.page_timeout,
                                                "load_timeout": config.load_timeout},
        name=f"docbox-bench-{run.id}", daemon=True,
    ).start()
    return run


def execute(
    run_id: str,
    *,
    install_missing: bool = False,
    page_timeout: float = PAGE_TIMEOUT_S,
    load_timeout: float = LOAD_TIMEOUT_S,
    on_progress: Progress | None = None,
) -> BenchRun:
    """Run a queued benchmark to the end on the calling thread."""
    run = store.load(run_id)
    run.state, run.pid = "running", os.getpid()
    store.save(run)
    notify = on_progress or (lambda _r: None)
    try:
        for model in run.models:
            if store.cancel_requested(run.id):
                break
            run.current_model_id = model.model_id
            _prepare(run, model, install_missing, notify)
            if model.state == "skipped":
                run.pages_done += run.pages_total
            else:
                _Worker(run, model, page_timeout, load_timeout, notify).run()
            run.current_model_id = None
            store.save(run)
            notify(run)
        run.state = "cancelled" if store.cancel_requested(run.id) else "done"
    except Exception as exc:
        run.state, run.error = "error", getattr(exc, "detail", None) or str(exc)
        _finish(run)
        raise
    _finish(run)
    notify(run)
    return run


def _finish(run: BenchRun) -> None:
    run.current_model_id = None
    run.finished_at = time.time()
    results = store.load_results(run.id)
    refs = store.load_references(run.id)
    run.summary = report.summarize(run, results, refs)
    store.save(run)
    store.write_report(run.id, report.to_markdown(run))


_NOT_READY = {
    "needs_download": "not installed",
    "needs_engine": "its engine isn't installed",
}


def _prepare(run: BenchRun, model: ModelRun, install_missing: bool, notify: Progress) -> None:
    """Install the model first if asked to; otherwise skip models that can't read now."""
    try:
        info = models_service.get_model(model.model_id)
        if info.status in _NOT_READY:
            if not install_missing:
                model.state = "skipped"
                model.error = f"{info.name} is {_NOT_READY[info.status]} (pass --install-missing / install_missing to install it)"
                return
            model.state = "installing"
            store.save(run)
            notify(run)
            models_service.install_model(model.model_id)
        elif info.status == "needs_prerequisite":
            model.state = "skipped"
            model.error = f"{info.name} needs {info.prerequisite} installed and running"
    except ServiceError as exc:
        model.state, model.error = "skipped", exc.detail


class _Worker:
    """One model's worker process, followed until it's done, stuck, crashed or cancelled."""

    def __init__(self, run: BenchRun, model: ModelRun, page_timeout: float,
                 load_timeout: float, notify: Progress) -> None:
        self.run_ = run
        self.model = model
        self.page_timeout = page_timeout
        self.load_timeout = load_timeout
        self.notify = notify
        # file id -> pages still to come from this model
        self.remaining = {f.id: f.pages for f in run.files}
        self.peak_bytes = 0

    def run(self) -> None:
        model, run = self.model, self.run_
        model.state = "running"
        store.save(run)
        self.notify(run)

        log_path = store.run_dir(run.id) / f"worker-{_safe(model.model_id)}.log"
        env = {**os.environ, "DOCBOX_DATA_DIR": str(get_data_dir()),
               "PYTHONIOENCODING": "utf-8"}
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "docbox.benchmark.worker"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                text=True, encoding="utf-8", errors="replace", env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            assert proc.stdin is not None and proc.stdout is not None
            # One line, and stdin stays open: the worker exits when it closes, so it never
            # outlives this process (see worker.py).
            job = {"model_id": model.model_id,
                   "files": [{"id": f.id, "path": f.path} for f in run.files],
                   "lifeline": True}
            proc.stdin.write(json.dumps(job) + "\n")
            proc.stdin.flush()

            events: queue.Queue[str | None] = queue.Queue()
            threading.Thread(target=_pump, args=(proc.stdout, events), daemon=True).start()
            sampler = threading.Thread(target=self._sample_memory, args=(proc,), daemon=True)
            sampler.start()
            try:
                outcome = self._follow(proc, events)
            finally:
                if proc.poll() is None:
                    _kill_tree(proc.pid)
                proc.wait()
                with contextlib.suppress(OSError):
                    proc.stdin.close()
                sampler.join(2)

        model.peak_memory_mb = round(self.peak_bytes / 2**20, 1) if self.peak_bytes else None
        if outcome == "crashed":
            tail = log_path.read_text(encoding="utf-8", errors="replace").strip()[-600:]
            model.error = f"The model stopped unexpectedly (exit code {proc.returncode})." + (
                f"\n{tail}" if tail else "")
        if outcome != "cancelled":
            # After "done" this only catches pages the worker never reported.
            self._fail_remaining(model.error or "No result for this page")
        if model.state == "running":
            model.state = "done" if outcome == "done" else "error"

    def _follow(self, proc: subprocess.Popen, events: queue.Queue[str | None]) -> str:
        """Read events until the worker says done; returns how it ended."""
        loaded = False
        last = time.monotonic()
        checked = last
        while True:
            timeout = self.page_timeout if loaded else self.load_timeout
            # Checked on a clock, not only when the worker goes quiet: a fast model sends a
            # page every few hundred ms and would otherwise never see the cancel.
            if time.monotonic() - checked >= 0.5:
                checked = time.monotonic()
                if store.cancel_requested(self.run_.id):
                    self.model.error = "Cancelled"
                    return "cancelled"
            try:
                line = events.get(timeout=0.5)
            except queue.Empty:
                if store.cancel_requested(self.run_.id):
                    self.model.error = "Cancelled"
                    return "cancelled"
                if time.monotonic() - last > timeout:
                    what = "a page" if loaded else "the model to load"
                    self.model.error = f"Timed out after {timeout:.0f} s waiting for {what}"
                    return "timeout"
                continue
            if line is None:  # stdout closed: the worker exited
                proc.wait()
                return "crashed"
            last = time.monotonic()
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("event")
            if kind == "loaded":
                loaded = True
                self.model.load_seconds = event.get("seconds")
            elif kind == "page":
                self._page(event)
            elif kind == "file_error":
                self._fail_file(event["file_id"], event.get("error") or "Can't read this file")
            elif kind == "fatal":
                self.model.state, self.model.error = "error", event.get("error")
                return "fatal"
            elif kind == "done":
                return "done"

    def _page(self, event: dict) -> None:
        result = PageResult(
            model_id=self.model.model_id, file_id=event["file_id"], page=event["page"],
            text=event.get("text") or "", lines=event.get("lines") or [],
            seconds=event.get("seconds"), error=event.get("error"),
        )
        store.append_result(self.run_.id, result)
        self.remaining[result.file_id] = max(0, self.remaining.get(result.file_id, 0) - 1)
        self.run_.pages_done += 1
        store.save(self.run_)
        self.notify(self.run_)

    def _fail_file(self, file_id: str, error: str) -> None:
        file = next(f for f in self.run_.files if f.id == file_id)
        left = self.remaining.get(file_id, 0)
        for page in range(file.pages - left + 1, file.pages + 1):
            store.append_result(self.run_.id, PageResult(
                model_id=self.model.model_id, file_id=file_id, page=page, error=error))
        self.remaining[file_id] = 0
        self.run_.pages_done += left
        store.save(self.run_)

    def _fail_remaining(self, error: str) -> None:
        for file_id, left in list(self.remaining.items()):
            if left:
                self._fail_file(file_id, error)

    def _sample_memory(self, proc: subprocess.Popen) -> None:
        try:
            ps = psutil.Process(proc.pid)
        except psutil.Error:
            return
        while proc.poll() is None:
            try:
                rss = ps.memory_info().rss + sum(
                    c.memory_info().rss for c in ps.children(recursive=True))
                self.peak_bytes = max(self.peak_bytes, rss)
            except psutil.Error:
                pass
            time.sleep(_MEMORY_SAMPLE_S)


def _pump(stream, events: queue.Queue[str | None]) -> None:
    for line in stream:
        events.put(line)
    events.put(None)


def _kill_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except psutil.Error:
        pass


def _safe(model_id: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in model_id)
