"""The OCR engine that was used last, kept loaded so the next read doesn't load the model
from disk again. Loading a model is often the slowest part of a short read, and reading a
batch of files with one model would otherwise pay for it once per file.

    with engine_cache.loaded(spec) as engine:
        result = engine.run(image)

Only one engine stays loaded (`_MAX_LOADED`): OCR models take 0.5–3 GB of RAM each, and
reading many files with one model is the common case. An engine nobody has used for
`idle_seconds()` is dropped. Each engine has its own lock, held while it's in use, so
runs on one engine never overlap: PaddleOCR and EasyOCR instances aren't safe to share
across threads.

Dropping an engine releases DocBox's references to it; the native libraries underneath
(Paddle, PyTorch) may keep some of their memory pooled until the process exits.

An engine whose model runs in another program (Ollama, a cloud API, an engine container:
`runs_in_process = False`) holds nothing here worth keeping, so it's neither cached nor
counted: reading with an Ollama model leaves the warm PaddleOCR model where it is.

The benchmark worker doesn't use this: it loads each model in a fresh process, which is
what makes its load-time and peak-memory numbers honest."""

from __future__ import annotations

import gc
import os
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from docbox.backend.core.registry import ModelSpec
from docbox.backend.engines.base import OCREngine

# One warm model: enough for reading many files with one model, and a second model in RAM
# would double the footprint on the 8 GB computers DocBox also runs on.
_MAX_LOADED = 1
# Long enough to cover a batch of files read one after another, short enough that a
# model doesn't sit in RAM all day after the last read. DOCBOX_ENGINE_IDLE_S overrides
# it; 0 keeps the engine until another model needs the room.
_DEFAULT_IDLE_S = 300.0


class NotDownloaded(Exception):
    """The model's files are gone (removed by this or another DocBox process)."""

    def __init__(self, spec: ModelSpec) -> None:
        super().__init__(f"{spec.name} is not downloaded yet")
        self.spec = spec


def idle_seconds() -> float:
    raw = os.environ.get("DOCBOX_ENGINE_IDLE_S")
    if raw is None:
        return _DEFAULT_IDLE_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_IDLE_S


@dataclass(eq=False)
class _Entry:
    model_id: str
    # The spec's factory identifies the engine: a model registered again (tests, plugins)
    # gets a new engine instead of the old one's.
    factory: Callable[[], OCREngine]
    engine: OCREngine
    lock: threading.Lock = field(default_factory=threading.Lock)
    loaded: bool = False
    # Uses that have ended. An idle timer remembers the count it was set for and lets the
    # engine go only if no use has ended since; it never asks the clock, which on Windows
    # (CPython 3.12) ticks every 15.6 ms and can say a timer woke before its time.
    uses: int = 0
    timer: threading.Timer | None = None


_entries: OrderedDict[str, _Entry] = OrderedDict()
_entries_lock = threading.Lock()


def _entry_for(spec: ModelSpec, engine: OCREngine) -> _Entry:
    """The cached entry for `spec`, or a new one around `engine` (a fresh instance)."""
    with _entries_lock:
        entry = _entries.get(spec.id)
        if entry is not None and entry.factory is not spec.engine_factory:
            _forget(entry)
            entry = None
        if entry is None:
            entry = _Entry(spec.id, spec.engine_factory, engine)
            _entries[spec.id] = entry
        _entries.move_to_end(spec.id)
        # Least recently used first. One still reading keeps its engine until it's done
        # (it holds its own reference); it just isn't offered to the next caller.
        while len(_entries) > _MAX_LOADED:
            _forget(next(iter(_entries.values())))
        return entry


def _forget(entry: _Entry) -> None:
    """Drop an entry from the cache (caller holds _entries_lock)."""
    if _entries.get(entry.model_id) is entry:
        del _entries[entry.model_id]
    if entry.timer is not None:
        entry.timer.cancel()
        entry.timer = None


@contextmanager
def loaded(spec: ModelSpec) -> Iterator[OCREngine]:
    """The model's engine, loaded, for exclusive use until the block ends. Raises
    NotDownloaded (and forgets the engine) when the model's files are gone."""
    engine = spec.engine_factory()  # cheap: building an engine doesn't load its model
    if not getattr(engine, "runs_in_process", True):
        if not engine.is_downloaded():
            raise NotDownloaded(spec)
        engine.load()
        yield engine
        return
    entry = _entry_for(spec, engine)
    try:
        with entry.lock:
            try:
                # Checked on every use: another process (the CLI, an agent) may have
                # removed the model since it was loaded.
                if not entry.engine.is_downloaded():
                    raise NotDownloaded(spec)
                if not entry.loaded:
                    entry.engine.load()
                    entry.loaded = True
            except BaseException:
                # Never keep an engine that failed to load or lost its files.
                with _entries_lock:
                    _forget(entry)
                raise
            try:
                yield entry.engine
            except BaseException:
                # A run that failed may have left the engine in a bad state: the next
                # read gets a fresh one, as it did before engines were kept.
                with _entries_lock:
                    _forget(entry)
                raise
            finally:
                entry.uses += 1
    finally:
        # Only once the lock is free: a timer that finds it held leaves the engine to
        # the use holding it, and this is where that use sets the next timer.
        _schedule_idle_unload(entry)


def _schedule_idle_unload(entry: _Entry) -> None:
    idle = idle_seconds()
    with _entries_lock:
        if entry.timer is not None:
            entry.timer.cancel()
            entry.timer = None
        if not idle or _entries.get(entry.model_id) is not entry:
            return
        entry.timer = threading.Timer(idle, _unload_if_idle, args=(entry, entry.uses))
        entry.timer.daemon = True
        entry.timer.start()


def _unload_if_idle(entry: _Entry, uses: int) -> None:
    # In use right now: that use sets a new timer once it's done.
    if not entry.lock.acquire(blocking=False):
        return
    try:
        with _entries_lock:
            # A use ended since this timer was set (one that fired as it was being
            # cancelled): the timer that use set decides.
            if entry.uses != uses:
                return
            _forget(entry)
    finally:
        entry.lock.release()
    del entry
    gc.collect()


def evict(model_id: str) -> None:
    """Drop the model's engine, waiting for a read that's using it to finish. Call it
    before deleting the model's files."""
    with _entries_lock:
        entry = _entries.get(model_id)
        if entry is None:
            return
        _forget(entry)
    # The read in progress (if any) finishes with its own reference; once it has, nothing
    # holds the engine any more.
    with entry.lock:
        pass
    del entry
    gc.collect()


def evict_all(model_ids: set[str] | None = None) -> None:
    """Drop every engine (or those of the given models), waiting for reads using them."""
    with _entries_lock:
        ids = [m for m in _entries if model_ids is None or m in model_ids]
    for model_id in ids:
        evict(model_id)


def loaded_model_ids() -> list[str]:
    """The models whose engines are cached, least recently used first."""
    with _entries_lock:
        return list(_entries)
