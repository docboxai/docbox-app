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


class ReadPageText(BaseModel):
    page: int
    text: str
    lines: list[OcrLine] | None = None


class ReadFileResult(BaseModel):
    file: str
    model_id: str
    text: str
    pages: list[ReadPageText]
    seconds: float | None
    output_path: str | None


@server.tool(annotations=_CHANGES)
def read_file(
    path: str,
    model_id: str | None = None,
    format: Literal["txt", "md", "json", "pdf"] = "txt",
    include_lines: bool = False,
) -> ReadFileResult:
    """Read the text of an image or PDF (every page) with one model, save it like the
    DocBox app does (in the output folder, as txt/md/json or a searchable pdf) and return
    the text. model_id defaults to the default model setting. include_lines adds each
    line's confidence and position."""
    model_id = model_id or settings_service.get_settings().default_model_id
    if not model_id:
        raise ToolError("invalid: no model_id given and no default model set")
    detail = _call(ocr.read_file, path, model_id, format)
    return ReadFileResult(
        file=path, model_id=model_id, text=detail.text, seconds=detail.seconds,
        output_path=detail.output_path,
        pages=[
            ReadPageText(page=n, text=p.text, lines=p.lines if include_lines else None)
            for n, p in enumerate(detail.pages, start=1)
        ],
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
