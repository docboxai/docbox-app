"""Reading whole files in the background: every page, one file at a time, saving the text
in the format the user picked. Files are read one at a time because OCR is CPU-heavy
and two at once would only make both slower."""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from docbox.backend import platforms
from docbox.backend.core import config_store, history, prerequisites, runtime
from docbox.backend.core.pages import PageError, count_pages, iter_pages
from docbox.backend.core.pdf_writer import PdfPage, write_searchable_pdf
from docbox.backend.core.registry import ModelSpec
from docbox.backend.engines.remote_engine import EngineServiceError
from docbox.backend.schemas import OutputFormat, ReadPage


class NotRunnable(Exception):
    # code: "not_found" | "blocked" (cloud switched off) | "needs_prerequisite" |
    # "conflict" (engine or weights not installed yet)
    def __init__(self, status_code: int, detail: str, code: str = "conflict") -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code


def check_runnable(model_id: str) -> ModelSpec:
    """The model's spec, if it can read a file right now; otherwise why not."""
    if platforms.cloud_blocked(model_id):
        raise NotRunnable(409, "The cloud engine is switched off", "blocked")
    try:
        spec = platforms.resolve_spec(model_id)
    except KeyError:
        raise NotRunnable(404, f"Unknown model: {model_id}", "not_found") from None
    if spec.requires_extra and not runtime.extra_installed(spec.requires_extra):
        raise NotRunnable(409, f"The {runtime.EXTRAS[spec.requires_extra][0]} isn't installed yet")
    if spec.prerequisite and not prerequisites.is_satisfied(spec.prerequisite):
        name = prerequisites.PREREQUISITES[spec.prerequisite]["name"]
        raise NotRunnable(409, f"{name} needs to be installed and running", "needs_prerequisite")
    return spec


@dataclass
class _Job:
    read_id: str
    model_id: str
    data: bytes
    content_type: str | None
    file_name: str
    output_format: OutputFormat
    # Where to save the output; None: the output folder from settings.
    out_dir: Path | None = None


_queue: queue.Queue[_Job] = queue.Queue()
_cancelled: set[str] = set()
_cancel_lock = threading.Lock()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def submit(
    *, file_name: str, data: bytes, content_type: str | None, spec: ModelSpec,
    output_format: OutputFormat,
):
    entry = history.create(file_name, spec.id, spec.name, output_format)
    _queue.put(_Job(entry.id, spec.id, data, content_type, file_name, output_format))
    _ensure_worker()
    return entry


def read_now(
    *, file_name: str, data: bytes, content_type: str | None, spec: ModelSpec,
    output_format: OutputFormat, out_dir: Path | None = None,
) -> str:
    """Read one file on the calling thread (the CLI and the MCP server, which wait for the
    answer) and return its read id. It is recorded in history like a read from the app;
    errors end up in its history entry, not raised."""
    entry = history.create(file_name, spec.id, spec.name, output_format)
    job = _Job(entry.id, spec.id, data, content_type, file_name, output_format, out_dir)
    try:
        _read(job)
    except KeyboardInterrupt:
        history.update(entry.id, state="cancelled")
        raise
    except Exception as exc:  # noqa: BLE001 — recorded like the background worker does
        history.update(entry.id, state="error", error=str(exc))
    return entry.id


def cancel(read_id: str) -> None:
    with _cancel_lock:
        _cancelled.add(read_id)


def _is_cancelled(read_id: str) -> bool:
    with _cancel_lock:
        return read_id in _cancelled


def _ensure_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="docbox-reader", daemon=True)
            _worker.start()


def _work() -> None:
    while True:
        job = _queue.get()
        try:
            _read(job)
        except Exception as exc:  # noqa: BLE001 — one bad file must not stop the queue
            history.update(job.read_id, state="error", error=str(exc))
        finally:
            with _cancel_lock:
                _cancelled.discard(job.read_id)
            _queue.task_done()


def _read(job: _Job) -> None:
    if _is_cancelled(job.read_id):
        history.update(job.read_id, state="cancelled")
        return
    started = time.monotonic()
    try:
        spec = check_runnable(job.model_id)
        total = count_pages(job.data, job.content_type, job.file_name)
    except (NotRunnable, PageError) as exc:
        history.update(job.read_id, state="error", error=str(exc))
        return
    history.update(job.read_id, state="reading", pages_total=total, pages_done=0)

    engine = spec.engine_factory()
    pages: list[ReadPage] = []
    pdf_pages: list[PdfPage] = []
    try:
        if not engine.is_downloaded():
            raise NotRunnable(409, f"{spec.name} is not downloaded yet")
        engine.load()
        for index, page in enumerate(iter_pages(job.data, job.content_type, job.file_name)):
            if _is_cancelled(job.read_id):
                history.update(job.read_id, state="cancelled")
                return
            result = engine.run(page.image)
            pages.append(ReadPage(lines=result.lines, text=result.text))
            if job.output_format == "pdf":
                pdf_pages.append(PdfPage(page.image, page.dpi, result.lines))
            history.update(job.read_id, pages_done=index + 1)
    except (NotRunnable, EngineServiceError) as exc:
        history.update(job.read_id, state="error", error=exc.detail)
        return

    output = _save_output(job, pages, pdf_pages)
    history.finish(
        job.read_id, pages, state="done", pages_done=len(pages),
        seconds=round(time.monotonic() - started, 2), output_path=str(output),
    )


# Characters Windows doesn't allow in file names, plus path separators everywhere.
_UNSAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _output_path(file_name: str, ext: str, folder: Path | None = None) -> Path:
    folder = folder or config_store.get_output_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stem = _UNSAFE_NAME.sub("_", Path(file_name).stem).strip(" .") or "document"
    path = folder / f"{stem}.{ext}"
    n = 2
    while path.exists():
        path = folder / f"{stem} ({n}).{ext}"
        n += 1
    return path


def render_text(file_name: str, pages: list[ReadPage], fmt: OutputFormat) -> str:
    if fmt == "md":
        if len(pages) == 1:
            return f"# {file_name}\n\n{pages[0].text}\n"
        parts = [f"## Page {i}\n\n{p.text}" for i, p in enumerate(pages, start=1)]
        return f"# {file_name}\n\n" + "\n\n".join(parts) + "\n"
    if fmt == "json":
        return json.dumps(
            {
                "file": file_name,
                "pages": [
                    {"page": i, "text": p.text, "lines": [ln.model_dump() for ln in p.lines]}
                    for i, p in enumerate(pages, start=1)
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    return "\n\n".join(p.text for p in pages) + "\n"


def _save_output(job: _Job, pages: list[ReadPage], pdf_pages: list[PdfPage]) -> Path:
    path = _output_path(job.file_name, job.output_format, job.out_dir)
    if job.output_format == "pdf":
        path.write_bytes(write_searchable_pdf(pdf_pages))
    else:
        # newline="\n": the same file on every OS (no CRLF on Windows).
        path.write_text(
            render_text(job.file_name, pages, job.output_format), encoding="utf-8", newline="\n"
        )
    return path
