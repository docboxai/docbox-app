"""DocBox as an MCP server, for AI agents: `docbox mcp` serves it over stdio.

Every tool is a thin wrapper over docbox.service (the same code the app and the CLI run).
Long work never blocks a tool call: installing a model and running a benchmark start in
the background and return an id the agent polls (get_install_status, get_benchmark).
Tools are plain functions, which the SDK runs on worker threads; it also keeps anything
an OCR library prints off the protocol's stdout.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from docbox import __version__
from docbox.backend.schemas import (
    DownloadStatus,
    EngineRemoveResult,
    ModelInfo,
    OcrLine,
    ReadDetail,
    Settings,
    SettingsUpdate,
    StorageInfo,
)
from docbox.benchmark.report import PageView
from docbox.benchmark.store import BenchRun
from docbox.service import benchmarks, engines, models, ocr
from docbox.service import settings as settings_service
from docbox.service.device import DeviceReport, device_info
from docbox.service.errors import ServiceError

INSTRUCTIONS = """\
DocBox runs open-source OCR models (PaddleOCR, Tesseract, EasyOCR, Ollama vision models)
on this computer and benchmarks them on the user's own documents.

Typical workflow to find the best model for a set of documents:
1. get_device, then list_models: pick models whose fit says they run well here.
2. install_model for any that aren't installed (status "needs_download" or "needs_engine"),
   then poll get_install_status until "done". Models with status "needs_prerequisite" need
   a program the user must install themselves (Tesseract or Ollama); tell them.
3. start_benchmark with the user's files or folders and the model ids. Reference text
   ("ground truth") is optional: invoice.gt.txt (whole document) or invoice.p2.gt.txt
   (page 2) next to invoice.pdf, or a manifest .json. Without it models are ranked by speed.
4. Poll get_benchmark until state is "done"; summary.leaderboard ranks the models.
   get_benchmark_page shows every model's reading of one page with its mistakes.
5. Suggest update_settings(default_model_id=best) if the user agrees.

To read documents: read_file answers directly for up to 5 pages; for longer ones call
start_read, then poll get_read until state is "done" and page through its text with
from_page / next_page. PDF pages that already carry text use it instead of OCR unless
use_pdf_text is false.

Paths are on the user's computer. Removing models or engines deletes files: confirm with
the user first. NVIDIA NIM models send images to NVIDIA's cloud and only work while the
cloud setting is on; don't turn it on without asking.
"""

server = MCPServer(
    name="docbox",
    title="DocBox",
    version=__version__,
    instructions=INSTRUCTIONS,
    website_url="https://github.com/docboxai/docbox-app",
)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
_CHANGES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
# Downloads from the internet (PyPI, model hosts).
_DOWNLOADS = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
_DELETES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ServiceError as exc:
        raise ToolError(f"{exc.code}: {exc.detail}") from None


# --- this computer and its models -------------------------------------------------------


@server.tool(annotations=_READ_ONLY)
def get_device() -> DeviceReport:
    """This computer's memory, processor, disk and GPU, and where DocBox keeps its data."""
    return device_info()


@server.tool(annotations=_READ_ONLY)
def list_models(
    status: Literal["ready", "needs_download", "needs_engine", "needs_prerequisite"]
    | None = None,
    fits_only: bool = False,
) -> list[ModelInfo]:
    """Every OCR model DocBox knows: whether it's installed (status), whether it fits this
    computer (fit), and which one is recommended here."""
    found = models.list_models()
    if status:
        found = [m for m in found if m.status == status]
    if fits_only:
        found = [m for m in found if m.fit.fits]
    return found


@server.tool(annotations=_READ_ONLY)
def get_model(model_id: str) -> ModelInfo:
    """One model in detail."""
    return _call(models.get_model, model_id)


@server.tool(annotations=_DOWNLOADS)
def install_model(model_id: str) -> DownloadStatus:
    """Start installing a model (its engine's packages the first time, then its weights).
    Returns at once with a job; poll get_install_status(job_id) until state is "done" or
    "error"."""
    return _call(models.start_install, model_id)


@server.tool(annotations=_READ_ONLY)
def get_install_status(job_id: str) -> DownloadStatus:
    """Progress of an install started with install_model."""
    return _call(models.install_status, job_id)


@server.tool(annotations=_DELETES)
def remove_model(model_id: str) -> str:
    """Delete a model's downloaded files. Ask the user first."""
    _call(models.remove_model, model_id)
    return f"Removed {model_id}"


@server.tool(annotations=_READ_ONLY)
def list_engines() -> StorageInfo:
    """Engine packages (PaddleOCR, EasyOCR) and the disk they and their models use."""
    return engines.storage()


@server.tool(annotations=_DELETES)
def remove_engine(engine: Literal["paddle", "easyocr"]) -> EngineRemoveResult:
    """Uninstall an engine and every model it downloaded. Ask the user first."""
    return _call(engines.remove_engine, engine)


# --- reading ----------------------------------------------------------------------------

# read_file waits for the whole document; longer ones go through start_read/get_read, so a
# tool call never outlasts the client's timeout.
_MAX_READ_FILE_PAGES = 5
# Text returned per call, in characters: about 5k tokens, well inside what agent clients
# accept in one tool result. The rest is fetched with from_page.
_DEFAULT_MAX_CHARS = 20_000
_MIN_MAX_CHARS, _MAX_MAX_CHARS = 1_000, 100_000


class ReadPageText(BaseModel):
    page: int
    text: str
    # "pdf_text": taken from the PDF itself, not read by the model.
    source: str = "ocr"
    # The page alone was longer than max_chars; the saved file has all of it.
    truncated: bool = False
    lines: list[OcrLine] | None = None


class ReadFileResult(BaseModel):
    file: str
    model_id: str
    read_id: str
    text: str
    pages: list[ReadPageText]
    # More pages than fit in max_chars: get_read(read_id, from_page=next_page) for the rest.
    next_page: int | None = None
    seconds: float | None
    output_path: str | None


class ReadStatus(BaseModel):
    read_id: str
    file: str
    model_id: str
    state: str
    pages_done: int
    pages_total: int | None
    error: str | None
    seconds: float | None
    output_path: str | None
    # Filled once the read is done, from from_page while they fit in max_chars.
    pages: list[ReadPageText]
    next_page: int | None = None


def _check_budget(from_page: int, max_chars: int) -> None:
    if from_page < 1:
        raise ToolError("invalid: from_page starts at 1")
    if not _MIN_MAX_CHARS <= max_chars <= _MAX_MAX_CHARS:
        raise ToolError(f"invalid: max_chars must be {_MIN_MAX_CHARS}-{_MAX_MAX_CHARS}")


def _pages_within(
    detail: ReadDetail, from_page: int, max_chars: int, include_lines: bool,
) -> tuple[list[ReadPageText], int | None]:
    """Whole pages from from_page while their text fits in max_chars (the first one is
    cut to fit if it alone is longer), and the page to continue from, if any."""
    out: list[ReadPageText] = []
    used = 0
    for n in range(from_page, len(detail.pages) + 1):
        page = detail.pages[n - 1]
        if out and used + len(page.text) > max_chars:
            return out, n
        truncated = len(page.text) > max_chars
        text = page.text[:max_chars] if truncated else page.text
        out.append(ReadPageText(page=n, text=text, source=page.source, truncated=truncated,
                                lines=page.lines if include_lines else None))
        used += len(text)
        if truncated:
            return out, n + 1 if n < len(detail.pages) else None
    return out, None


@server.tool(annotations=_CHANGES)
def read_file(
    path: str,
    model_id: str | None = None,
    format: Literal["txt", "md", "json", "pdf"] = "txt",
    include_lines: bool = False,
    use_pdf_text: bool = True,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> ReadFileResult:
    """Read the text of an image or a PDF of up to 5 pages with one model, save it like the
    DocBox app does (in the output folder, as txt/md/json or a searchable pdf) and return
    the text. Longer documents: use start_read. model_id defaults to the default model
    setting. PDF pages that carry their own text use it unless use_pdf_text is false.
    include_lines adds each line's confidence and position. At most max_chars of text
    come back; next_page says where get_read continues."""
    _check_budget(1, max_chars)
    model_id = model_id or settings_service.get_settings().default_model_id
    if not model_id:
        raise ToolError("invalid: no model_id given and no default model set")
    pages = _call(ocr.page_count, path)
    if pages > _MAX_READ_FILE_PAGES:
        raise ToolError(
            f"invalid: this document has {pages} pages; read_file waits for at most "
            f"{_MAX_READ_FILE_PAGES}. Use start_read, then get_read."
        )
    detail = _call(ocr.read_file, path, model_id, format, use_pdf_text=use_pdf_text)
    shown, next_page = _pages_within(detail, 1, max_chars, include_lines)
    return ReadFileResult(
        file=path, model_id=model_id, read_id=detail.id, text="\n\n".join(p.text for p in shown),
        pages=shown, next_page=next_page, seconds=detail.seconds,
        output_path=detail.output_path,
    )


@server.tool(annotations=_CHANGES)
def start_read(
    path: str,
    model_id: str | None = None,
    format: Literal["txt", "md", "json", "pdf"] = "txt",
    use_pdf_text: bool = True,
) -> ReadStatus:
    """Start reading an image or PDF of any length in the background and return at once;
    poll get_read(read_id) until state is "done" (or "error"). The text is saved like
    read_file saves it. model_id defaults to the default model setting."""
    model_id = model_id or settings_service.get_settings().default_model_id
    if not model_id:
        raise ToolError("invalid: no model_id given and no default model set")
    entry = _call(ocr.start_read, path, model_id, format, use_pdf_text=use_pdf_text)
    return ReadStatus(
        read_id=entry.id, file=path, model_id=entry.model_id, state=entry.state,
        pages_done=entry.pages_done, pages_total=entry.pages_total, error=entry.error,
        seconds=entry.seconds, output_path=entry.output_path, pages=[],
    )


@server.tool(annotations=_READ_ONLY)
def get_read(
    read_id: str,
    from_page: int = 1,
    max_chars: int = _DEFAULT_MAX_CHARS,
    include_lines: bool = False,
) -> ReadStatus:
    """A read's progress (pages_done of pages_total) and, once state is "done", its text:
    whole pages from from_page while they fit in max_chars. Call again with
    from_page=next_page for the rest."""
    _check_budget(from_page, max_chars)
    detail = _call(ocr.get_read, read_id)
    shown, next_page = (
        _pages_within(detail, from_page, max_chars, include_lines)
        if detail.state == "done" else ([], None)
    )
    return ReadStatus(
        read_id=detail.id, file=detail.file_name, model_id=detail.model_id,
        state=detail.state, pages_done=detail.pages_done, pages_total=detail.pages_total,
        error=detail.error, seconds=detail.seconds, output_path=detail.output_path,
        pages=shown, next_page=next_page,
    )


# --- settings ---------------------------------------------------------------------------


@server.tool(annotations=_READ_ONLY)
def get_settings() -> Settings:
    """The default model, the cloud-engine switch and the output folder."""
    return settings_service.get_settings()


@server.tool(annotations=_CHANGES)
def update_settings(
    default_model_id: str | None = None, cloud_enabled: bool | None = None,
) -> Settings:
    """Change the default model ("" clears it) and/or the cloud-engine switch (NVIDIA NIM
    sends images to NVIDIA's cloud: only turn it on when the user asks)."""
    return _call(settings_service.update_settings,
                 SettingsUpdate(default_model_id=default_model_id, cloud_enabled=cloud_enabled))


# --- benchmarks -------------------------------------------------------------------------


class BenchmarkBrief(BaseModel):
    id: str
    name: str
    state: str
    created_at: float
    files: int
    pages_total: int
    models: list[str]
    best_model_id: str | None


def _brief(run: BenchRun) -> BenchmarkBrief:
    return BenchmarkBrief(
        id=run.id, name=run.name, state=run.state, created_at=run.created_at,
        files=len(run.files), pages_total=run.pages_total,
        models=[m.model_id for m in run.models],
        best_model_id=run.summary.best_model_id if run.summary else None,
    )


@server.tool(annotations=_DOWNLOADS)
def start_benchmark(
    paths: list[str],
    models: list[str] | None = None,
    name: str | None = None,
    recursive: bool = False,
    install_missing: bool = False,
    ignore_case: bool = False,
) -> BenchRun:
    """Benchmark OCR models on files, folders or manifests: each model reads every page
    (one model at a time, each in its own process). models defaults to every installed
    model. Returns at once; poll get_benchmark(id) until state is "done". With
    install_missing, models that aren't installed are installed first (downloads)."""
    config = benchmarks.BenchConfig(
        sources=paths, models=models or [], name=name, recursive=recursive,
        install_missing=install_missing, ignore_case=ignore_case, source="mcp",
    )
    return _call(benchmarks.start, config)


@server.tool(annotations=_READ_ONLY)
def get_benchmark(run_id: str) -> BenchRun:
    """A benchmark's state and progress (pages_done of pages_total × models) and its
    leaderboard (summary), live while it runs."""
    return _call(benchmarks.get, run_id)


@server.tool(annotations=_READ_ONLY)
def get_benchmark_page(
    run_id: str, file_id: str, page: int = 1, against: str | None = None,
) -> PageView:
    """Every model's reading of one page, with its mistakes ("slips") against the
    reference text. Without a reference, pass against=<model_id> to compare with that
    model's reading. file_id is from the benchmark's files list."""
    return _call(benchmarks.page, run_id, file_id, page, against)


@server.tool(annotations=_READ_ONLY)
def list_benchmarks() -> list[BenchmarkBrief]:
    """Saved benchmark runs, newest first."""
    return [_brief(r) for r in benchmarks.list_runs()]


@server.tool(annotations=_CHANGES)
def cancel_benchmark(run_id: str) -> BenchmarkBrief:
    """Stop a running benchmark; pages read so far are kept."""
    return _brief(_call(benchmarks.cancel, run_id))


@server.tool(annotations=_DELETES)
def delete_benchmark(run_id: str) -> str:
    """Delete a saved benchmark run."""
    _call(benchmarks.delete, run_id)
    return f"Deleted {run_id}"


@server.resource(
    "docbox://benchmarks/{run_id}/report", name="benchmark_report", mime_type="text/markdown",
    description="A benchmark's report: leaderboard, problems and files, as Markdown.",
)
def benchmark_report(run_id: str) -> str:
    return _call(benchmarks.render_report, run_id, "md")


def serve() -> None:
    server.run("stdio")
