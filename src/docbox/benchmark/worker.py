"""One model reading every page of a benchmark, in its own process:

    python -m docbox.benchmark.worker  < job.json

The job on stdin: {"model_id": "...", "files": [{"id": "...", "path": "..."}]}.
Events on stdout, one JSON object per line:

    {"event": "loaded", "seconds": 1.9, "in_process": true}  false: the model runs in
                                                         another program (Ollama, cloud)
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

import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from typing import TextIO


def _protocol_stream() -> TextIO:
    out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return out


def main() -> int:
    proto = _protocol_stream()

    def emit(event: str, **fields) -> None:
        proto.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
        proto.flush()

    job = json.loads(sys.stdin.read())
    from docbox import plugins

    plugins.load()

    from docbox.backend.core.pages import iter_pages
    from docbox.service import ocr
    from docbox.service.errors import ServiceError

    try:
        spec = ocr.check_runnable(job["model_id"])
        # A fresh engine in a fresh process, never the reader's warm one (engine_cache):
        # that's what makes the load time and peak memory honest. Pages always go through
        # OCR (iter_pages, not iter_read_pages), even when a PDF carries its own text.
        engine = spec.engine_factory()
        started = time.perf_counter()
        engine.load()
        emit("loaded", seconds=round(time.perf_counter() - started, 3),
             in_process=getattr(engine, "runs_in_process", True))
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
