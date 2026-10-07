"""Asking before destructive actions."""

from __future__ import annotations

import sys

from docbox.service.errors import Invalid


def confirm(question: str, *, yes: bool) -> bool:
    """True to go ahead. With no terminal to ask (an agent, a script) and no --yes, refuse
    rather than wait forever for an answer."""
    if yes:
        return True
    if not sys.stdin.isatty():
        raise Invalid(f"{question} Pass --yes to confirm (there's no terminal to ask).")
    answer = input(f"{question} [y/N] ").strip().lower()
    return answer in ("y", "yes")
