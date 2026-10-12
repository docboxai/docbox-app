"""Waiting for stdin to close: how the backend and benchmark workers notice that whoever
started them is gone.

On Windows this must not be a blocking read. While a thread waits in ReadFile on a
synchronous pipe, anything else that touches the standard handles waits behind it, and a
DLL's C runtime does that as it loads: importing numpy (paddle, torch) then hangs for ever,
holding the loader lock. So on Windows the pipe is polled with PeekNamedPipe, which never
leaves a read pending, and EOF shows up as a failed peek (ERROR_BROKEN_PIPE).
"""

from __future__ import annotations

import contextlib
import os
import sys
import time

# How often Windows checks the pipe. Noticing the app has gone this much later is fine.
_POLL_S = 0.5


def wait_for_stdin_close() -> None:
    """Return once stdin reaches EOF (or can't be read any more). Discards anything
    written to it."""
    with contextlib.suppress(OSError, ValueError):
        fd = sys.stdin.fileno()
        if sys.platform == "win32" and _is_pipe(fd):
            _poll_pipe(fd)
        else:
            while os.read(fd, 65536):
                pass


def _is_pipe(fd: int) -> bool:
    import ctypes
    import msvcrt

    file_type_pipe = 3
    return ctypes.windll.kernel32.GetFileType(msvcrt.get_osfhandle(fd)) == file_type_pipe


def _poll_pipe(fd: int) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    peek = ctypes.windll.kernel32.PeekNamedPipe
    peek.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                     ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    peek.restype = wintypes.BOOL
    handle = msvcrt.get_osfhandle(fd)
    available = wintypes.DWORD()
    while peek(handle, None, 0, None, ctypes.byref(available), None):
        if available.value:
            # Bytes are waiting, so this read returns at once rather than staying pending.
            os.read(fd, available.value)
        else:
            time.sleep(_POLL_S)
