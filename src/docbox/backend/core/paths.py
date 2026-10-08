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


# A macOS app opened from Finder gets a bare PATH without Homebrew's folders (Apple
# Silicon, then Intel), so programs installed with `brew` are looked for there too.
MACOS_BIN_DIRS = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))


# The desktop app's bundle identifier (tauri.conf.json); Tauri names its per-user data
# folder after it and passes that folder to the backend as DOCBOX_DATA_DIR.
APP_IDENTIFIER = "io.github.docboxai.docbox"


def desktop_app_data_dir() -> Path:
    """Where the installed desktop app keeps its data: Tauri's app_local_data_dir, which
    is %LOCALAPPDATA%\\<id> on Windows, ~/Library/Application Support/<id> on macOS and
    $XDG_DATA_HOME/<id> on Linux."""
    return Path(platformdirs.user_data_dir(appname=APP_IDENTIFIER, appauthor=False))


def get_data_dir() -> Path:
    """DOCBOX_DATA_DIR, else the desktop app's folder when the app has been run here (so the
    `docbox` CLI and MCP server share its models, history and benchmarks), else
    platformdirs' own per-OS data dir."""
    override = os.environ.get("DOCBOX_DATA_DIR")
    if override:
        d = Path(override)
    elif desktop_app_data_dir().is_dir():
        d = desktop_app_data_dir()
    else:
        d = Path(platformdirs.user_data_dir(appname=_APP_NAME, appauthor=_APP_AUTHOR))
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
    # (installed app, Docker, tests) or the app's own folder is a different install and
    # must not swallow it.
    if (
        not d.exists()
        and not os.environ.get("DOCBOX_DATA_DIR")
        and d.parent != desktop_app_data_dir()
    ):
        _migrate_legacy_models_dir(d)
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_runtime_dir() -> Path:
    d = get_data_dir() / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    return d
