"""docbox mcp [config <client>]"""

from __future__ import annotations

import json
import shlex
import shutil
import sys
from pathlib import Path

from docbox.cli.output import Output

CLIENTS = ("claude-code", "claude-desktop", "cursor", "vscode")


def register(sub, common) -> None:
    p = sub.add_parser(
        "mcp", help="serve DocBox to AI agents over MCP (stdio)",
        description="With no command, serve the MCP server on stdin/stdout. Point an MCP "
        "client at `docbox mcp`; `docbox mcp config <client>` prints the setup.",
    )
    p.set_defaults(func=_serve)
    msub = p.add_subparsers(dest="command", metavar="<command>")
    cfg = msub.add_parser("config", parents=[common], help="print the setup for an MCP client")
    cfg.add_argument("client", choices=CLIENTS)
    cfg.set_defaults(func=_config)


def _serve(args, out: Output) -> int:
    from docbox.mcp_server import serve

    serve()
    return 0


def _command() -> list[str]:
    """How to start this docbox: its own executable when installed, else this Python."""
    exe = Path(sys.argv[0])
    if exe.name in ("docbox", "docbox.exe") and exe.exists():
        return [str(exe.resolve()), "mcp"]
    found = shutil.which("docbox")
    if found:
        return [found, "mcp"]
    return [sys.executable, "-m", "docbox.cli", "mcp"]


def _config(args, out: Output) -> int:
    command, *cmd_args = _command()
    server = {"command": command, "args": cmd_args}
    if args.client == "claude-code":
        text = f"claude mcp add docbox -- {shlex.join([command, *cmd_args])}"
        value: object = {"command": text}
    elif args.client == "vscode":
        value = {"servers": {"docbox": {"type": "stdio", **server}}}
        text = (f"Add to .vscode/mcp.json (or your user MCP settings):\n\n"
                f"{json.dumps(value, indent=2)}")
    else:
        where = {
            "claude-desktop": "claude_desktop_config.json (Settings › Developer › Edit Config)",
            "cursor": "~/.cursor/mcp.json (or .cursor/mcp.json in a project)",
        }[args.client]
        value = {"mcpServers": {"docbox": server}}
        text = f"Add to {where}:\n\n{json.dumps(value, indent=2)}"
    out.result(value, lambda: print(text))
    return 0
