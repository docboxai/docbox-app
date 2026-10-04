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


def get_default_model_id() -> str | None:
    return _read().get("default_model_id") or None


def set_default_model_id(model_id: str | None) -> None:
    data = _read()
    if model_id:
        data["default_model_id"] = model_id
    else:
        data.pop("default_model_id", None)
    _write(data)


def cloud_enabled() -> bool:
    """Whether cloud engines (NVIDIA NIM) may be listed and run. Users who saved a key
    before this switch existed keep their cloud models: an unset switch follows the key."""
    value = _read().get("cloud_enabled")
    if value is None:
        return get_nvidia_api_key() is not None
    return bool(value)


def set_cloud_enabled(enabled: bool) -> None:
    data = _read()
    data["cloud_enabled"] = enabled
    _write(data)


def get_output_dir() -> Path:
    custom = _read().get("output_dir")
    if custom:
        return Path(custom)
    return Path(platformdirs.user_documents_dir()) / _APP_NAME


def set_output_dir(path: str | None) -> None:
    data = _read()
    if path:
        data["output_dir"] = path
    else:
        data.pop("output_dir", None)
    _write(data)
