"""The backend, and everything it starts, never outlives the desktop shell that started it.

These run the real backend in a subprocess, the way the shell does."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

# Never through an HTTP(S)_PROXY from the environment: these talk to 127.0.0.1.
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_backend(data_dir: Path, *args: str) -> tuple[subprocess.Popen, int]:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "docbox.backend.main", "--port", str(port), *args],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, "DOCBOX_DATA_DIR": str(data_dir)},
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"the backend exited before it was ready (code {proc.returncode})")
        try:
            with _NO_PROXY.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as resp:
                if resp.status == 200:
                    return proc, port
        except OSError:
            time.sleep(0.2)
    proc.kill()
    pytest.fail("the backend never answered /api/health")


def test_backend_exits_when_the_shell_closes_its_stdin(data_dir: Path) -> None:
    proc, _port = _start_backend(data_dir, "--exit-on-stdin-close")
    try:
        assert proc.stdin is not None
        proc.stdin.close()  # what happens when the shell exits, crashes or is killed
        assert proc.wait(timeout=15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_without_the_flag_stdin_closing_changes_nothing(data_dir: Path) -> None:
    # A backend run by hand or in Docker keeps serving whatever its stdin does.
    proc, port = _start_backend(data_dir)
    try:
        assert proc.stdin is not None
        proc.stdin.close()
        time.sleep(2)
        assert proc.poll() is None
        with _NO_PROXY.open(f"http://127.0.0.1:{port}/api/health", timeout=5) as resp:
            assert resp.status == 200
    finally:
        proc.terminate()
        proc.wait(timeout=15)


def test_stop_children_ends_what_the_backend_started(data_dir: Path) -> None:
    script = (
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "from docbox.backend.main import stop_children\n"
        "stop_children()\n"
        "print(child.poll() is not None)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60,
        env={**os.environ, "DOCBOX_DATA_DIR": str(data_dir)}, check=True,
    )
    assert out.stdout.strip() == "True"
