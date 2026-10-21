"""What the engines' graphics-card builds need before their libraries load.

Paddle's Windows wheel looks for NVIDIA's CUDA and cuDNN libraries on the DLL search path,
where a system-wide CUDA toolkit would put them. DocBox installs them as NVIDIA's own
wheels instead (pyproject.toml's `paddle-gpu` extra), whose DLLs sit in
`site-packages/nvidia/<library>/bin`: `add_nvidia_dll_dirs()` puts those on the search path
(and on PATH, which Paddle's loader searches) before Paddle is imported. Elsewhere, and
without those wheels, it does nothing.
"""

from __future__ import annotations

import functools
import os
import sys
import sysconfig
from pathlib import Path


@functools.lru_cache(maxsize=1)
def add_nvidia_dll_dirs() -> tuple[str, ...]:
    if sys.platform != "win32":
        return ()
    root = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
    dirs = tuple(str(d) for d in sorted(root.glob("*/bin")) if d.is_dir())
    for d in dirs:
        os.add_dll_directory(d)
    if dirs:
        os.environ["PATH"] = os.pathsep.join([*dirs, os.environ.get("PATH", "")])
    return dirs
