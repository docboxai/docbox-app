"""The backend, and everything it starts, never outlives the desktop shell that started it,
and it tells the shell which port it listens on.

These run the real backend in a subprocess, the way the shell does."""

from __future__ import annotations

import json
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


def _wait_healthy(proc: subprocess.Popen, port: int) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"the backend exited before it was ready (code {proc.returncode})")
        try:
            with _NO_PROXY.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    proc.kill()
    pytest.fail("the backend never answered /api/health")


def _start_like_the_shell(data_dir: Path) -> tuple[subprocess.Popen, int]:
    """`--port 0 --exit-on-stdin-close`, stdin and stdout piped: what main.rs runs."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "docbox.backend.main", "--port", "0", "--exit-on-stdin-close"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        env={**os.environ, "DOCBOX_DATA_DIR": str(data_dir)},
    )
    assert proc.stdout is not None
    report = json.loads(proc.stdout.readline())
    port = report["docbox_backend"]["port"]
    _wait_healthy(proc, port)
    return proc, port


def test_backend_reports_the_port_the_os_picked(data_dir: Path) -> None:
    proc, port = _start_like_the_shell(data_dir)
    try:
        assert 0 < port < 65536
        with _NO_PROXY.open(f"http://127.0.0.1:{port}/api/health", timeout=5) as resp:
            assert json.loads(resp.read())["status"] == "ok"
    finally:
        proc.kill()
        proc.wait(timeout=15)


def test_backend_exits_when_the_shell_closes_its_stdin(data_dir: Path) -> None:
    proc, _port = _start_like_the_shell(data_dir)
    try:
        assert proc.stdin is not None
        proc.stdin.close()  # what happens when the shell exits, crashes or is killed
        assert proc.wait(timeout=15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_run_by_hand_it_keeps_its_port_and_ignores_stdin(data_dir: Path) -> None:
    # A backend started in a terminal or in Docker: a fixed port, no lifeline.
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "docbox.backend.main", "--port", str(port)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, "DOCBOX_DATA_DIR": str(data_dir)},
    )
    try:
        _wait_healthy(proc, port)
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
