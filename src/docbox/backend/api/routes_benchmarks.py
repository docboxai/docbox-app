"""Benchmarks for the app's Benchmarks view: start one from uploaded files, follow it,
compare one page across models. Runs started by the CLI or an agent (MCP) show up too:
they share the data dir."""

from __future__ import annotations

import io
import re
from pathlib import PurePosixPath
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from docbox.backend.api.errors import http_errors
from docbox.benchmark import store
from docbox.benchmark.reference import ReferenceData, reference
from docbox.benchmark.report import PageView
from docbox.benchmark.store import BenchRun
from docbox.service import benchmarks as service

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])

_UNSAFE_PART = re.compile(r'[<>:"\\|?*\x00-\x1f]')


def _relative_upload_path(name: str) -> PurePosixPath:
    """Where an uploaded file goes inside the run's inputs folder. The app sends a dropped
    folder's files as "folder/sub/file.png", so sidecar references stay next to their
    documents; anything that could climb out of the folder is dropped."""
    parts = [
        _UNSAFE_PART.sub("_", p).strip(" .")
        for p in name.replace("\\", "/").split("/")
        if p not in ("", ".", "..")
    ]
    parts = [p for p in parts if p]
    if not parts:
        raise HTTPException(status_code=400, detail=f"Bad file name: {name!r}")
    return PurePosixPath(*parts)


@router.post("", response_model=BenchRun, status_code=202)
def start_benchmark(
    files: list[UploadFile] = File(...),
    model_ids: str = Form("", description="comma-separated; empty: every ready model"),
    name: str = Form(""),
    ignore_case: bool = Form(False),
) -> BenchRun:
    # Every name is checked before anything is written, and the run's folder goes again if
    # anything after that fails (a write error, a refused model), so a failed start never
    # leaves files behind that no listing shows.
    placed = [(f, _relative_upload_path(f.filename or "document")) for f in files]
    tops = {rel.parts[0] if len(rel.parts) > 1 else "" for _f, rel in placed}
    # One dropped folder names the run after itself.
    folder_name = next(iter(tops)) if len(tops) == 1 else ""
    run_id = store.new_id()
    try:
        inputs = store.inputs_dir(run_id)
        for f, rel in placed:
            target = inputs.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f.file.read())
        config = service.BenchConfig(
            sources=[inputs], models=[m for m in model_ids.split(",") if m.strip()],
            name=name.strip() or folder_name or None, recursive=True, ignore_case=ignore_case,
            source="app", run_id=run_id,
        )
        with http_errors():
            return service.start(config)
    except BaseException:
        store.delete_folder(run_id)
        raise


@router.get("", response_model=list[BenchRun])
def list_benchmarks() -> list[BenchRun]:
    return service.list_runs()


# Before /{run_id}, which would otherwise take "reference" as a run id.
@router.get("/reference", response_model=ReferenceData)
def get_reference() -> ReferenceData:
    """Published OCRBench v1/v2 scores for catalog models, for the benchmark graph."""
    return reference()


@router.get("/{run_id}", response_model=BenchRun)
def get_benchmark(run_id: str) -> BenchRun:
    with http_errors():
        return service.get(run_id)


@router.get("/{run_id}/page", response_model=PageView)
def get_page(run_id: str, file_id: str, page: int = 1, against: str | None = None) -> PageView:
    with http_errors():
        return service.page(run_id, file_id, page, against)


@router.get("/{run_id}/image")
def get_page_image(run_id: str, file_id: str, page: int = 1) -> Response:
    with http_errors():
        image = service.page_image(run_id, file_id, page)
    # A preview, not the original: small enough to send quickly, sharp enough to read.
    image.thumbnail((1400, 1400))
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG", optimize=True)
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{run_id}/report")
def get_report(run_id: str, format: Literal["md", "csv", "json"] = "md") -> Response:
    with http_errors():
        text = service.render_report(run_id, format)
    media = {"md": "text/markdown", "csv": "text/csv", "json": "application/json"}[format]
    return Response(content=text, media_type=f"{media}; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="docbox-benchmark-{run_id}.{format}"'})


@router.post("/{run_id}/cancel", response_model=BenchRun)
def cancel_benchmark(run_id: str) -> BenchRun:
    with http_errors():
        return service.cancel(run_id)


@router.post("/{run_id}/rerun", response_model=BenchRun, status_code=202)
def rerun_benchmark(run_id: str) -> BenchRun:
    with http_errors():
        return service.rerun(run_id, source="app")


@router.delete("/{run_id}", status_code=204)
def delete_benchmark(run_id: str) -> Response:
    with http_errors():
        service.delete(run_id)
    return Response(status_code=204)
