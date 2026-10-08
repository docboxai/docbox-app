"""One model reading every page of a benchmark, in its own process:

    python -m docbox.benchmark.worker  < job.json

The job on stdin: {"model_id": "...", "files": [{"id": "...", "path": "..."}]}, either
as its first line or as the whole of stdin. The runner sends it as one line, adds
"lifeline": true and keeps stdin open: the worker exits as soon as stdin closes, so it
never outlives the process that started it (an app that was closed or crashed, a killed
CLI). Without "lifeline", stdin may end right after the job, as with `< job.json`.
Events on stdout, one JSON object per line:

    {"event": "loaded", "seconds": 1.9}
    {"event": "page", "file_id": "...", "page": 1, "text": "...", "lines": [...],
     "seconds": 0.4}                                  (or "error": "..." instead of text)
    {"event": "file_error", "file_id": "...", "error": "..."}
    {"event": "fatal", "error": "...", "code": "..."}  the model can't run at all
    {"event": "done"}

A process per model gives honest peak-memory numbers, frees the model's memory when it
ends, keeps a crash or hang to that model, and leaves no native libraries loaded in the
process that started it (which on Windows would lock their files).

OCR libraries print progress and warnings to stdout; the events go to a private copy of
the original stdout and everything else printed is sent to stderr.

Modules named in DOCBOX_PRELOAD are imported first (docbox/plugins.py), so models
registered outside the built-in catalog can run here too.
"""

from __future__ import annotations

import contextlib
import json
import mimetypes
import os
import sys
import threading
import time
from pathlib import Path
from typing import TextIO


def _protocol_stream() -> TextIO:
    out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return out


def _read_job() -> dict:
    first = sys.stdin.readline()
    try:
        return json.loads(first)
    except ValueError:
        # Not one line: a job written out by hand, which ends where stdin does.
        return json.loads(first + sys.stdin.read())


def _exit_when_stdin_closes() -> None:
    def watch() -> None:
        with contextlib.suppress(OSError, ValueError):
            sys.stdin.read()
        # Whoever started this worker is gone; nobody will read its pages.
        os._exit(1)

    threading.Thread(target=watch, name="docbox-worker-lifeline", daemon=True).start()


def main() -> int:
    proto = _protocol_stream()

    def emit(event: str, **fields) -> None:
        proto.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
        proto.flush()

    job = _read_job()
    if job.get("lifeline"):
        _exit_when_stdin_closes()
    from docbox import plugins
    from docbox.backend.core import tls

    tls.use_system_certificates()
    plugins.load()

    from docbox.backend.core.pages import iter_pages
    from docbox.service import ocr
    from docbox.service.errors import ServiceError

    try:
        spec = ocr.check_runnable(job["model_id"])
        engine = spec.engine_factory()
        started = time.perf_counter()
        engine.load()
        emit("loaded", seconds=round(time.perf_counter() - started, 3))
    except ServiceError as exc:
        emit("fatal", error=exc.detail, code=exc.code)
        return 1
    except Exception as exc:  # noqa: BLE001 — whatever the engine's library raised
        emit("fatal", error=f"{type(exc).__name__}: {exc}", code="failed")
        return 1

    for file in job["files"]:
        path = Path(file["path"])
        try:
            data = path.read_bytes()
            pages = iter_pages(data, mimetypes.guess_type(path.name)[0], path.name)
            for n, page in enumerate(pages, start=1):
                started = time.perf_counter()
                try:
                    result = engine.run(page.image)
                except Exception as exc:  # noqa: BLE001 — one bad page, not the whole file
                    emit("page", file_id=file["id"], page=n,
                         error=f"{type(exc).__name__}: {exc}",
                         seconds=round(time.perf_counter() - started, 3))
                    continue
                emit("page", file_id=file["id"], page=n, text=result.text,
                     lines=[line.model_dump() for line in result.lines],
                     seconds=round(time.perf_counter() - started, 3))
        except Exception as exc:  # noqa: BLE001 — unreadable file: report it, read the rest
            emit("file_error", file_id=file["id"], error=f"{type(exc).__name__}: {exc}")

    emit("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
