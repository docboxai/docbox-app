"""Tiny local settings file for things that aren't downloadable models — currently just
an optional NVIDIA NIM API key. Stored as plain JSON under the per-OS user config
directory (the same trust model as e.g. `gh`'s or `aws`'s local config files: readable by
the local user account, not a system keychain). Never logged, never sent anywhere except
as the Authorization header on requests this app makes directly to NVIDIA's API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import platformdirs

_APP_NAME = "DocBox"
_APP_AUTHOR = "docbox"


def _settings_path() -> Path:
    d = Path(platformdirs.user_config_dir(appname=_APP_NAME, appauthor=_APP_AUTHOR))
    d.mkdir(parents=True, exist_ok=True)
    return d / "settings.json"


def _read() -> dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write(data: dict[str, Any]) -> None:
    _settings_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_nvidia_api_key() -> str | None:
    return _read().get("nvidia_nim_api_key") or None


def set_nvidia_api_key(api_key: str) -> None:
    data = _read()
    data["nvidia_nim_api_key"] = api_key
    _write(data)


def clear_nvidia_api_key() -> None:
    data = _read()
    data.pop("nvidia_nim_api_key", None)
    _write(data)
