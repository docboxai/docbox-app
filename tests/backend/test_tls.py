"""HTTPS from DocBox's Python processes verifies against the OS trust store (core/tls.py).

Checked in fresh interpreters: in this test process another test may already have done it."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from docbox.backend.core import tls


def _python(code: str, data_dir: Path) -> list[str]:
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
        env={**os.environ, "DOCBOX_DATA_DIR": str(data_dir)}, check=True,
    )
    return out.stdout.strip().splitlines()


_CHECK = (
    "import ssl, truststore, urllib3.util.ssl_ as u\n"
    "print(ssl.SSLContext is truststore.SSLContext and u.SSLContext is truststore.SSLContext)\n"
)


def test_the_backend_uses_the_os_trust_store(data_dir: Path) -> None:
    assert _python("import docbox.backend.main\n" + _CHECK, data_dir)[-1] == "True"


def test_the_cli_uses_the_os_trust_store(data_dir: Path) -> None:
    code = "from docbox.cli.main import main\nmain(['--json', 'device'])\n" + _CHECK
    assert _python(code, data_dir)[-1] == "True"


def test_it_can_be_called_from_every_entry_point() -> None:
    tls.use_system_certificates()
    tls.use_system_certificates()  # the backend and a worker in one process: no error

    import ssl

    import truststore

    assert ssl.SSLContext is truststore.SSLContext
