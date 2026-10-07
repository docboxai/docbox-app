"""Printing results: a table or a few lines for people, JSON for agents and scripts."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel

from docbox.service.errors import Blocked, NeedsPrerequisite, ServiceError

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NEEDS_PREREQUISITE = 3
EXIT_BLOCKED = 4


def exit_code(exc: ServiceError) -> int:
    if isinstance(exc, NeedsPrerequisite):
        return EXIT_NEEDS_PREREQUISITE
    if isinstance(exc, Blocked):
        return EXIT_BLOCKED
    return EXIT_ERROR


def to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


class Output:
    def __init__(self, as_json: bool) -> None:
        self.json = as_json

    def result(self, value: Any, human: Callable[[], None] | None = None) -> None:
        """The command's result: JSON on stdout, or `human()` prints it for people."""
        if self.json:
            json.dump(to_jsonable(value), sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
        elif human is not None:
            human()

    def error(self, code: str, detail: str) -> None:
        if self.json:
            json.dump({"error": {"code": code, "detail": detail}}, sys.stderr)
            sys.stderr.write("\n")
        else:
            print(f"docbox: {detail}", file=sys.stderr)

    def progress(self, message: str) -> None:
        """A transient status line, only when a person is watching a terminal."""
        if not self.json and sys.stderr.isatty():
            sys.stderr.write(f"\r\033[K{message}")
            sys.stderr.flush()

    def end_progress(self) -> None:
        if not self.json and sys.stderr.isatty():
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    cells = [[str(c) for c in headers], *[["" if c is None else str(c) for c in r] for r in rows]]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    for n, row in enumerate(cells):
        print("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip())
        if n == 0:
            print("  ".join("-" * w for w in widths))


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
