"""Files the user has read: a small index for the Recent files list plus one JSON file per
read holding its text. Lives in the data dir (`<data>/history/`), never leaves this
computer, and can be cleared per entry."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from docbox.backend.core.paths import get_data_dir
from docbox.backend.schemas import OutputFormat, ReadDetail, ReadPage, ReadSummary

# Older entries fall off the end; their saved output files stay where they were saved.
_MAX_ENTRIES = 200
_UNFINISHED = ("queued", "reading")

_lock = threading.Lock()


def _dir() -> Path:
    d = get_data_dir() / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path() -> Path:
    return _dir() / "index.json"


def _detail_path(read_id: str) -> Path:
    # Ids are uuid4 hex we generated; reject anything else so an id can't name a path.
    if not (len(read_id) == 32 and all(c in "0123456789abcdef" for c in read_id)):
        raise KeyError(read_id)
    return _dir() / f"{read_id}.json"


def _load_index() -> list[ReadSummary]:
    try:
        raw = json.loads(_index_path().read_text(encoding="utf-8"))
        return [ReadSummary.model_validate(item) for item in raw]
    except (OSError, ValueError):
        return []


def _save_index(entries: list[ReadSummary]) -> None:
    tmp = _index_path().with_suffix(".tmp")
    tmp.write_text(json.dumps([e.model_dump() for e in entries]), encoding="utf-8")
    tmp.replace(_index_path())


def create(file_name: str, model_id: str, model_name: str, fmt: OutputFormat) -> ReadSummary:
    entry = ReadSummary(
        id=uuid.uuid4().hex,
        file_name=file_name,
        model_id=model_id,
        model_name=model_name,
        output_format=fmt,
        state="queued",
        created_at=time.time(),
    )
    with _lock:
        entries = [entry, *_load_index()]
        for dropped in entries[_MAX_ENTRIES:]:
            _detail_path(dropped.id).unlink(missing_ok=True)
        _save_index(entries[:_MAX_ENTRIES])
    return entry


def update(read_id: str, **fields) -> ReadSummary | None:
    with _lock:
        entries = _load_index()
        for i, entry in enumerate(entries):
            if entry.id == read_id:
                entries[i] = entry.model_copy(update=fields)
                _save_index(entries)
                return entries[i]
    return None


def finish(read_id: str, pages: list[ReadPage], **fields) -> ReadSummary | None:
    entry = update(read_id, **fields)
    if entry is not None:
        detail = ReadDetail(
            **entry.model_dump(), pages=pages, text="\n\n".join(p.text for p in pages)
        )
        _detail_path(read_id).write_text(detail.model_dump_json(), encoding="utf-8")
    return entry


def list_reads() -> list[ReadSummary]:
    with _lock:
        return _load_index()


def get(read_id: str) -> ReadSummary | None:
    return next((e for e in list_reads() if e.id == read_id), None)


def get_detail(read_id: str) -> ReadDetail | None:
    entry = get(read_id)
    if entry is None:
        return None
    try:
        stored = ReadDetail.model_validate_json(_detail_path(read_id).read_text("utf-8"))
    except (OSError, ValueError):
        return ReadDetail(**entry.model_dump())
    # The index is the source of truth for state; the detail file holds the text.
    return ReadDetail(**entry.model_dump(), pages=stored.pages, text=stored.text)


def delete(read_id: str) -> bool:
    with _lock:
        entries = _load_index()
        kept = [e for e in entries if e.id != read_id]
        if len(kept) == len(entries):
            return False
        _save_index(kept)
    _detail_path(read_id).unlink(missing_ok=True)
    return True


def mark_interrupted() -> None:
    """Reads still queued or running when the backend last stopped will never finish."""
    with _lock:
        entries = _load_index()
        changed = False
        for i, entry in enumerate(entries):
            if entry.state in _UNFINISHED:
                entries[i] = entry.model_copy(
                    update={"state": "error", "error": "DocBox closed before this finished"}
                )
                changed = True
        if changed:
            _save_index(entries)
