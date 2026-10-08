"""Locks shared between DocBox processes. The desktop app's backend, the `docbox` CLI
and the MCP server all write the same data dir (read history, settings, model files), so
a thread lock isn't enough: these are lock files the OS releases if a process dies."""

from __future__ import annotations

import re
from pathlib import Path

from filelock import FileLock, Timeout

from docbox.backend.core.paths import get_data_dir

__all__ = ["Timeout", "data_lock", "model_lock"]


def _locks_dir() -> Path:
    d = get_data_dir() / "locks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def data_lock(name: str, timeout: float = 30) -> FileLock:
    """Held around a read-modify-write of a shared file, e.g. data_lock("history")."""
    return FileLock(_locks_dir() / f"{name}.lock", timeout=timeout)


def model_lock(model_id: str) -> FileLock:
    """Held while a model is being installed; non-blocking (acquire raises Timeout), so a
    second process says "already being installed" instead of waiting on a long job."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", model_id)
    return FileLock(_locks_dir() / f"model-{safe}.lock", timeout=0)
