"""Reading files from disk, for front ends that wait for the answer (the CLI and the MCP
server). Reads are recorded in history like reads from the app, so they show under
Recent files."""

from __future__ import annotations

import mimetypes
from collections.abc import Iterable, Iterator
from pathlib import Path

import docbox.backend.models_catalog  # noqa: F401 — importing it fills the registry
from docbox.backend.core import history, reader
from docbox.backend.core.registry import ModelSpec
from docbox.backend.engines.remote_engine import EngineServiceError
from docbox.backend.schemas import OutputFormat, ReadDetail
from docbox.service.errors import (
    Blocked,
    Conflict,
    Failed,
    Invalid,
    NeedsPrerequisite,
    NotFound,
    ServiceError,
    Unavailable,
)

# What a read can take: PDFs and the image formats Pillow opens.
SUPPORTED_SUFFIXES = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
)

_NOT_RUNNABLE: dict[str, type[ServiceError]] = {
    "not_found": NotFound,
    "blocked": Blocked,
    "needs_prerequisite": NeedsPrerequisite,
}


def check_runnable(model_id: str) -> ModelSpec:
    """The model's spec if it can read right now: known, allowed, engine and weights
    installed, external program running."""
    try:
        spec = reader.check_runnable(model_id)
    except reader.NotRunnable as exc:
        raise _NOT_RUNNABLE.get(exc.code, Conflict)(exc.detail) from None
    try:
        downloaded = spec.engine_factory().is_downloaded()
    except EngineServiceError as exc:
        raise Unavailable(exc.detail) from None
    if not downloaded:
        raise Conflict(f"{spec.name} is not downloaded yet (docbox models install {spec.id})")
    return spec


def collect_files(paths: Iterable[str | Path], *, recursive: bool = False) -> list[Path]:
    """The readable files among `paths`: files as given, and the supported files in each
    folder (and its subfolders with `recursive`), sorted, without duplicates."""
    found: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            found += sorted(
                p for p in path.glob(pattern)
                if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
            )
        elif path.is_file():
            found.append(path)
        else:
            raise NotFound(f"No such file or folder: {path}")
    seen: set[Path] = set()
    unique = []
    for p in found:
        key = p.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def read_file(
    path: str | Path, model_id: str, fmt: OutputFormat = "txt", out_dir: Path | None = None,
) -> ReadDetail:
    """Read every page of one file with one model and save the text, like Read a file in
    the app. Raises when the model can't run or the read fails."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise NotFound(f"No such file: {path}")
    return _read_checked(path, check_runnable(model_id), fmt, out_dir)


def _read_checked(
    path: Path, spec: ModelSpec, fmt: OutputFormat, out_dir: Path | None,
) -> ReadDetail:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise Invalid(f"Can't read {path}: {exc}") from None
    content_type = mimetypes.guess_type(path.name)[0]
    read_id = reader.read_now(
        file_name=path.name, data=data, content_type=content_type, spec=spec,
        output_format=fmt, out_dir=out_dir,
    )
    detail = history.get_detail(read_id)
    if detail is None:  # pushed out of history by 200 newer reads in the meantime
        raise Failed("The read finished but its record is gone")
    if detail.state != "done":
        raise Failed(detail.error or f"The read ended as {detail.state}")
    return detail


def read_files(
    paths: Iterable[Path], model_id: str, fmt: OutputFormat = "txt", out_dir: Path | None = None,
) -> Iterator[tuple[Path, ReadDetail | ServiceError]]:
    """Each file's read, or the error that stopped it; one bad file doesn't stop the rest
    (but a model that can't run at all stops them all, raised before the first file)."""
    # Checked once for the whole batch (for Ollama that's a request to its server); the
    # reader still confirms the weights are there before each file.
    spec = check_runnable(model_id)
    for path in paths:
        path = Path(path).expanduser()
        try:
            if not path.is_file():
                raise NotFound(f"No such file: {path}")
            yield path, _read_checked(path, spec, fmt, out_dir)
        except (Failed, Invalid, NotFound) as exc:
            yield path, exc
