"""Asking before destructive actions."""

from __future__ import annotations

import sys

from docbox.service.errors import Invalid


def confirm(question: str, *, yes: bool) -> bool:
    """True to go ahead. With no terminal to ask (an agent, a script) and no --yes, refuse
    rather than wait forever for an answer."""
    if yes:
        return True
    no_terminal = Invalid(f"{question} Pass --yes to confirm (there's no terminal to ask).")
    if not sys.stdin.isatty():
        raise no_terminal
    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except EOFError:
        # Windows calls NUL a terminal, so stdin redirected from it gets this far.
        raise no_terminal from None
    return answer in ("y", "yes")
