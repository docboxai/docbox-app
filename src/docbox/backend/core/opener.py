"""Showing a file or folder in the user's own file manager or default app."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(str(path))
    if sys.platform == "win32":
        os.startfile(str(path))  # opens with the user's default app
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen(
        [opener, str(path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
