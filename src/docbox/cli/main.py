"""Entry point: `docbox <group> <command> ...`."""

from __future__ import annotations

import argparse
import sys

from docbox import __version__
from docbox.cli.commands import device, engines, models, read, settings
from docbox.cli.output import EXIT_ERROR, EXIT_USAGE, Output, exit_code
from docbox.service.errors import ServiceError

_GROUPS = (device, models, engines, read, settings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docbox",
        description="Read text from images and PDFs with local OCR models, and benchmark "
        "the models on your own documents.",
        epilog="Every command takes --json for machine-readable output. Exit codes: 0 ok, "
        "1 error, 2 usage, 3 needs an external program (Tesseract, Ollama), 4 blocked "
        "(cloud engine off, doesn't fit).",
    )
    parser.add_argument("--version", action="version", version=f"docbox {__version__}")
    # --json works before or after the command: `docbox --json models list` and
    # `docbox models list --json`.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS,
        help="print the result as JSON (errors as JSON on stderr)",
    )
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="group", metavar="<command>", required=True)
    for group in _GROUPS:
        group.register(sub, common)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help, --version, or a usage error
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    out = Output(as_json=bool(getattr(args, "json", False)))
    try:
        return args.func(args, out) or 0
    except ServiceError as exc:
        out.end_progress()
        out.error(exc.code, exc.detail)
        return exit_code(exc)
    except KeyboardInterrupt:
        out.end_progress()
        out.error("interrupted", "Stopped.")
        return 130
    except Exception as exc:  # noqa: BLE001 — one line instead of a traceback
        out.end_progress()
        out.error("error", f"{type(exc).__name__}: {exc}")
        return EXIT_ERROR


def run() -> None:
    sys.exit(main())


__all__ = ["EXIT_USAGE", "build_parser", "main", "run"]
