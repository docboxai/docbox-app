"""Tiny local settings file for things that aren't downloadable models: an optional
NVIDIA NIM API key, the default model, the cloud-engine switch and the folder finished
reads are saved to. Stored as plain JSON under the per-OS user config
directory (the same trust model as e.g. `gh`'s or `aws`'s local config files: readable by
the local user account, not a system keychain). Never logged, never sent anywhere except
as the Authorization header on requests this app makes directly to NVIDIA's API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import platformdirs
from filelock import FileLock

from docbox.backend.core import atomic

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
        return json.loads(atomic.read_text(path))
    except (json.JSONDecodeError, OSError):
        return {}


def _write(data: dict[str, Any]) -> None:
    path = _settings_path()
    atomic.write_text(path, json.dumps(data, indent=2))


def _locked() -> FileLock:
    # The app's backend, the CLI and the MCP server can all change settings: each change
    # is a read-modify-write under this lock so one doesn't undo another's.
    return FileLock(_settings_path().with_suffix(".lock"), timeout=30)


def _update(**changes: Any) -> None:
    """Set keys (a value of None removes the key)."""
    with _locked():
        data = _read()
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        _write(data)


def get_nvidia_api_key() -> str | None:
    return _read().get("nvidia_nim_api_key") or None


def set_nvidia_api_key(api_key: str) -> None:
    _update(nvidia_nim_api_key=api_key)


def clear_nvidia_api_key() -> None:
    _update(nvidia_nim_api_key=None)


def get_default_model_id() -> str | None:
    return _read().get("default_model_id") or None


def set_default_model_id(model_id: str | None) -> None:
    _update(default_model_id=model_id or None)


def cloud_enabled() -> bool:
    """Whether cloud engines (NVIDIA NIM) may be listed and run. Users who saved a key
    before this switch existed keep their cloud models: an unset switch follows the key."""
    value = _read().get("cloud_enabled")
    if value is None:
        return get_nvidia_api_key() is not None
    return bool(value)


def set_cloud_enabled(enabled: bool) -> None:
    _update(cloud_enabled=enabled)


def get_output_dir() -> Path:
    custom = _read().get("output_dir")
    if custom:
        return Path(custom)
    return Path(platformdirs.user_documents_dir()) / _APP_NAME


def set_output_dir(path: str | None) -> None:
    _update(output_dir=path or None)
