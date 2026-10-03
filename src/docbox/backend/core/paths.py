"""Where DocBox keeps its data: downloaded models, runtime state.

Models live in a *data* dir, not a cache dir — they're multi-GB files the user chose to
keep, and OS cleanup tools are free to wipe cache dirs. The installed app sets
`DOCBOX_DATA_DIR` to its own per-user data folder; dev runs and Docker fall back to
platformdirs' per-OS data dir (Docker sets it to its `/data` volume).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import platformdirs

_APP_NAME = "DocBox"
_APP_AUTHOR = "docbox"


def get_data_dir() -> Path:
    override = os.environ.get("DOCBOX_DATA_DIR")
    d = Path(override) if override else Path(
        platformdirs.user_data_dir(appname=_APP_NAME, appauthor=_APP_AUTHOR)
    )
    d.mkdir(parents=True, exist_ok=True)
    return d


def _migrate_legacy_models_dir(new: Path) -> None:
    # Earlier versions stored models under the per-OS *cache* dir.
    old = Path(platformdirs.user_cache_dir(appname=_APP_NAME, appauthor=_APP_AUTHOR)) / "models"
    if old.is_dir() and not new.exists() and old.resolve() != new.resolve():
        shutil.move(str(old), str(new))


def get_models_dir() -> Path:
    d = get_data_dir() / "models"
    # Only the default location inherits the old cache dir; an explicit DOCBOX_DATA_DIR
    # (installed app, Docker, tests) is a different install and must not swallow it.
    if not d.exists() and not os.environ.get("DOCBOX_DATA_DIR"):
        _migrate_legacy_models_dir(d)
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_runtime_dir() -> Path:
    d = get_data_dir() / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    return d
