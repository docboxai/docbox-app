"""The MCP server comes with the `agents` extra: a plain install, and the desktop app's
managed runtime, don't have its SDK."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from docbox.backend.core import runtime
from docbox.cli.commands import mcp as mcp_command
from docbox.cli.main import main


def test_docbox_mcp_without_the_extra_says_how_to_install_it(capsys, monkeypatch) -> None:
    monkeypatch.setattr(mcp_command, "_mcp_installed", lambda: False)
    assert main(["--json", "mcp"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert error["code"] == "unavailable"
    assert mcp_command.INSTALL_AGENTS in error["detail"]


def test_mcp_config_without_the_extra_prints_the_setup_and_what_to_install(
    capsys, monkeypatch,
) -> None:
    monkeypatch.setattr(mcp_command, "_mcp_installed", lambda: False)
    assert main(["mcp", "config", "cursor"]) == 0
    printed = capsys.readouterr()
    assert '"docbox"' in printed.out
    assert mcp_command.INSTALL_AGENTS in printed.err


def test_the_cli_imports_the_mcp_sdk_only_to_serve(data_dir: Path) -> None:
    code = (
        "import sys\n"
        "from docbox.cli.main import main\n"
        "main(['--help'])\n"
        "main(['--json', 'device'])\n"
        "main(['mcp', 'config', 'claude-code'])\n"
        "print('mcp' in sys.modules or 'docbox.mcp_server' in sys.modules)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
        env={**os.environ, "DOCBOX_DATA_DIR": str(data_dir)}, check=True,
    )
    assert out.stdout.strip().splitlines()[-1] == "False"


def test_removing_an_engine_keeps_what_the_mcp_server_needs() -> None:
    # PaddleOCR and the MCP SDK share packages the base install doesn't have (attrs). In
    # tool mode, removing the engine uninstalls what only it needs; that must not break
    # `docbox mcp`.
    if not runtime.extra_installed("paddle"):
        pytest.skip("needs the paddle extra (CI and `uv sync --extra paddle` have it)")
    mcp_dists = runtime._dist_closure(("mcp",))
    assert mcp_dists, "the dev group installs the MCP SDK"
    assert not runtime._exclusive_dists("paddle") & mcp_dists
