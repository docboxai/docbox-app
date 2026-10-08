"""Whole-file JSON writes that readers in other threads and processes never see half done.

A file is written beside its destination and renamed over it. On Windows a rename onto a
file someone has open, or a read of a file mid-rename, fails with PermissionError for a
moment; both retry for up to a second rather than calling the file missing or broken.
"""

from __future__ import annotations

import time
from pathlib import Path

_TRIES = 50
_PAUSE = 0.02


def write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(_TRIES):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == _TRIES - 1:
                raise
            time.sleep(_PAUSE)


def read_text(path: Path) -> str:
    for attempt in range(_TRIES):
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError:
            if attempt == _TRIES - 1:
                raise
            time.sleep(_PAUSE)
    raise AssertionError("unreachable")
