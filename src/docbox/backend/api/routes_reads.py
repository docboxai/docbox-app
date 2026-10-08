"""Reading whole files (every page) in the background, and the history of reads."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from docbox.backend.core import history, reader
from docbox.backend.core.opener import open_path
from docbox.backend.schemas import OutputFormat, ReadDetail, ReadStartResponse, ReadSummary

router = APIRouter(prefix="/api/reads", tags=["reads"])


@router.post("", response_model=ReadStartResponse, status_code=202)
def start_reads(
    files: list[UploadFile] = File(...),
    model_id: str = Form(...),
    output_format: OutputFormat = Form("txt"),
    # False reads every PDF page with the model, even pages that carry their own text.
    use_pdf_text: bool = Form(True),
) -> ReadStartResponse:
    try:
        spec = reader.check_runnable(model_id)
    except reader.NotRunnable as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    reads = [
        reader.submit(
            file_name=Path(f.filename or "document").name,
            data=f.file.read(),
            content_type=f.content_type,
            spec=spec,
            output_format=output_format,
            use_pdf_text=use_pdf_text,
        )
        for f in files
    ]
    return ReadStartResponse(reads=reads)


@router.get("", response_model=list[ReadSummary])
def list_reads() -> list[ReadSummary]:
    return history.list_reads()


@router.get("/{read_id}", response_model=ReadDetail)
def get_read(read_id: str) -> ReadDetail:
    detail = history.get_detail(read_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Unknown read")
    return detail


@router.delete("/{read_id}", status_code=204)
def delete_read(read_id: str) -> Response:
    """Forget a read (stopping it first if it's still going). The saved file is the
    user's, so it stays where it is."""
    reader.cancel(read_id)
    if not history.delete(read_id):
        raise HTTPException(status_code=404, detail="Unknown read")
    return Response(status_code=204)


def _saved_file(read_id: str) -> Path:
    # Only paths DocBox itself recorded for this read: the client names a read, not a path.
    entry = history.get(read_id)
    if entry is None or not entry.output_path:
        raise HTTPException(status_code=404, detail="This read has no saved file")
    return Path(entry.output_path)


@router.get("/{read_id}/file")
def download_read(read_id: str) -> FileResponse:
    """The saved file itself, for a browser on another device: opening it with
    /open would show it on the computer running DocBox, not to the person asking."""
    path = _saved_file(read_id)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="The saved file was moved or deleted")
    return FileResponse(path, filename=path.name)


@router.post("/{read_id}/open", status_code=204)
def open_read(read_id: str, target: Literal["file", "folder"] = "file") -> Response:
    """Open the saved file (or its folder) on the computer running DocBox."""
    path = _saved_file(read_id)
    try:
        open_path(path if target == "file" else path.parent)
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="The saved file was moved or deleted")
    return Response(status_code=204)
