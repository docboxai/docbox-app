"""HTTPS from Python trusts the operating system's certificates, as browsers do.

Downloads (Tesseract language data, PaddleOCR and EasyOCR weights, NVIDIA's API) otherwise
trust only the CA bundle that ships with certifi. Behind a company proxy that inspects HTTPS
with its own CA, which IT installs into the OS store, that's the difference between them
working and failing with CERTIFICATE_VERIFY_FAILED. uv gets the same from the shell's
`UV_SYSTEM_CERTS`.
"""

from __future__ import annotations

import threading

import truststore

_lock = threading.Lock()
_done = False


def use_system_certificates() -> None:
    """Make ssl, urllib3 and requests verify against the OS trust store. Idempotent: every
    entry point calls it (the backend, the CLI, benchmark workers)."""
    global _done
    with _lock:
        if not _done:
            truststore.inject_into_ssl()
            _done = True
