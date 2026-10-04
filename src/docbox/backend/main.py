"""FastAPI app factory and the `python -m docbox.backend.main` uvicorn entrypoint."""

from __future__ import annotations

import argparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from docbox.backend.api import (
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
from docbox.backend.schemas import HealthStatus


def create_app() -> FastAPI:
    app = FastAPI(title="DocBox Backend", version="0.1.0")

    # This server only ever listens on 127.0.0.1 and serves a single local desktop
    # app (Tauri webview origins like http://localhost:1420 in dev or
    # http://tauri.localhost in a built app) -- there's no third-party origin or
    # credential exposure to guard against, so a permissive policy is fine here.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    history.mark_interrupted()

    # Importing the catalog registers the concrete ModelSpec entries as a side effect.
    from docbox.backend import models_catalog  # noqa: F401

    return app


app = create_app()


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the DocBox backend server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8756)
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
