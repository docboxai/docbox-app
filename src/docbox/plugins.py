"""Models registered outside the built-in catalog: DOCBOX_PRELOAD names modules
(comma-separated, importable from PYTHONPATH) that register ModelSpecs when imported.
Every DocBox process imports them first (the CLI, the MCP server, benchmark workers), so
such a model works everywhere a built-in one does. Tests use it for fake engines."""

from __future__ import annotations

import importlib
import os


def load() -> None:
    for module in filter(None, (m.strip() for m in os.environ.get("DOCBOX_PRELOAD", "").split(","))):
        importlib.import_module(module)
