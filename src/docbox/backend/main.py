"""FastAPI app factory and the `python -m docbox.backend.main` uvicorn entrypoint."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import psutil
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from docbox.backend.api import (
    routes_benchmarks,
    routes_device,
    routes_engines,
    routes_models,
    routes_ocr,
    routes_platforms,
    routes_prerequisites,
    routes_reads,
    routes_settings,
)
from docbox.backend.core import history
from docbox.backend.core.client_header import CLIENT_HEADER
from docbox.backend.schemas import HealthStatus

if TYPE_CHECKING:
    import uvicorn

# Tauri 2's webview origin: tauri://localhost on Linux/macOS, http://tauri.localhost on
# Windows. Plus the Vite dev server for `npm run dev`.
_APP_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
]


# The Host header every legitimate caller sends: the webview and the Vite proxy both
# address the backend as 127.0.0.1:<port>.
_APP_HOSTS = ["127.0.0.1", "localhost"]

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _env_list(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


def _allowed_origins() -> list[str]:
    # DOCBOX_CORS_ORIGINS (comma-separated) adds origins, e.g. a client served elsewhere
    # that talks to the Docker backend.
    return _APP_ORIGINS + _env_list("DOCBOX_CORS_ORIGINS")


def _allowed_hosts() -> list[str]:
    # DOCBOX_ALLOWED_HOSTS adds hostnames, e.g. a Docker engine container's service name.
    return _APP_HOSTS + _env_list("DOCBOX_ALLOWED_HOSTS")


def _cross_site(request: Request) -> bool:
    """A browser request from another website. Browsers attach Origin to every
    cross-site POST, but can't add CLIENT_HEADER without a CORS preflight that other
    origins fail. Requests without Origin (curl, scripts, RemoteEngine) and from the
    backend's own pages (Swagger UI at /docs) are not cross-site."""
    if request.headers.get(CLIENT_HEADER):
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return False
    return origin != f"{request.url.scheme}://{request.headers.get('host', '')}"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Startup work runs when a server starts, not whenever an app object is built (tests
    # build many, and must not touch the user's real read history).
    history.mark_interrupted()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="DocBox Backend", version="0.1.0", lifespan=_lifespan)

    # Middleware added last runs first: Host check, then CORS, then the cross-site check.
    @app.middleware("http")
    async def refuse_cross_site_writes(request: Request, call_next):
        if request.method not in _SAFE_METHODS and _cross_site(request):
            return JSONResponse(
                status_code=403,
                content={"detail": f"Cross-site request refused (send {CLIENT_HEADER})"},
            )
        return await call_next(request)

    # The server listens on 127.0.0.1 only, but a web page in the user's browser can
    # still reach loopback, and the read history holds the text of the user's documents.
    # CORS stops other origins reading responses...
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # ...and the Host check stops DNS rebinding, where another site's hostname resolves
    # to 127.0.0.1 so the browser treats it as same-origin and CORS never applies.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts())

    @app.get("/api/health", response_model=HealthStatus)
    def health() -> HealthStatus:
        return HealthStatus()

    app.include_router(routes_device.router)
    app.include_router(routes_models.router)
    app.include_router(routes_ocr.router)
    app.include_router(routes_platforms.router)
    app.include_router(routes_prerequisites.router)
    app.include_router(routes_engines.router)
    app.include_router(routes_reads.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_benchmarks.router)

    # Importing the catalog registers the concrete ModelSpec entries as a side effect.
    from docbox.backend import models_catalog  # noqa: F401

    return app


app = create_app()

# After the shell is gone: how long a graceful shutdown may take before the process just
# exits (a request stuck in a long OCR call would otherwise keep it waiting).
_EXIT_GRACE_S = 5.0
# How long the backend's children get to exit on terminate() before they're killed.
_CHILD_GRACE_S = 3.0


def stop_children() -> None:
    """End every process this backend started and is still running (engine installs,
    benchmark workers), so none of them outlives it."""
    try:
        children = psutil.Process().children(recursive=True)
    except psutil.Error:
        return
    for child in children:
        with contextlib.suppress(psutil.Error):
            child.terminate()
    _gone, alive = psutil.wait_procs(children, timeout=_CHILD_GRACE_S)
    for child in alive:
        with contextlib.suppress(psutil.Error):
            child.kill()


def _exit_when_stdin_closes(server: uvicorn.Server) -> None:
    """The desktop shell keeps this process's stdin open and never writes to it, so EOF
    means the shell is gone: closed, crashed or force-quit. Stop then, instead of running
    on as an orphan that holds the CPU, the port and the model files."""

    def watch() -> None:
        with contextlib.suppress(OSError, ValueError):
            sys.stdin.buffer.read()
        stop_children()
        server.should_exit = True
        hard_exit = threading.Timer(_EXIT_GRACE_S, os._exit, args=(0,))
        hard_exit.daemon = True
        hard_exit.start()

    threading.Thread(target=watch, name="docbox-lifeline", daemon=True).start()


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the DocBox backend server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8756)
    parser.add_argument(
        "--exit-on-stdin-close", action="store_true",
        help="shut down when stdin reaches EOF (the desktop app holds it open while it runs)",
    )
    args = parser.parse_args()

    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="info"))
    if args.exit_on_stdin_close:
        _exit_when_stdin_closes(server)
    server.run()


if __name__ == "__main__":
    main()
