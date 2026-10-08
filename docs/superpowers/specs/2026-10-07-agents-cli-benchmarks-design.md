# DocBox for agents: CLI, benchmarks, MCP server and a Benchmarks view

Date: 2026-10-07 · Branch: `feature/agents-cli-benchmarks` · Related: issue #5

## Goal

Let external AI agents (Claude Code, Cursor, Claude Desktop, …) drive DocBox — check the
device, install and remove models, read files and, above all, **benchmark OCR models on
the user's own documents** — through a `docbox` CLI and an MCP server. The desktop app
gets a Benchmarks view (the "local OCR test bench" from the design's landing frames) that
shows the same saved runs.

### Decisions (agreed)

| Topic | Decision |
|---|---|
| Who drives it | External agents, over MCP (stdio) or by running the CLI |
| Benchmark measures | Speed, memory, confidence always; CER/WER when reference text is given |
| Runtime | In-process: the CLI/MCP run engines themselves, no desktop app needed |
| Agent permissions | Full control: install/remove models and engines, change settings |
| Distribution | Standalone (`uv tool install` / `uvx`) now; launcher bundled with the app later |
| Datasets | The user's own files/folders; `.gt.txt` sidecars **and** a manifest; public benchmark sets later via a pluggable source |
| Results | Saved runs under the data dir, shared by CLI, MCP and the app |
| Architecture | Approach A: one `docbox.service` layer; HTTP routes, CLI and MCP are thin front ends |

### Out of scope (later)

Public benchmark datasets (FUNSD, SROIE, …), the app-bundled `docbox` launcher, GPU
inference, an agent loop inside DocBox.

## 1. Service layer and CLI  *(approved)*

```
src/docbox/
  backend/      existing FastAPI app; routes become thin wrappers over service/
  service/      plain-Python operations, no FastAPI imports
    errors.py   ServiceError(code, detail): NotFound | Conflict | Unavailable | Invalid
    models.py   list_models, get_model, install_model, remove_model
    engines.py  storage(), remove_engine()
    device.py   device_info()
    ocr.py      read_file(path, model_id, fmt, out_dir) -> ReadDetail (synchronous)
    settings.py get_settings(), update_settings()
  cli/          argparse (no new dependency); entry point `docbox`
```

- Logic moves out of `api/routes_*.py` into `service/`; routes map `ServiceError` codes to
  404/409/503/400, so **the HTTP API is unchanged** and the existing route tests guard the
  refactor.
- The HTTP download keeps its background job store. The CLI calls the same
  `install_model(progress_cb)` in the foreground and renders progress; Ctrl+C stops it.

### Commands (every command takes `--json`)

```
docbox device
docbox models list [--ready] [--fits]
docbox models show <id>
docbox models install <id>
docbox models remove <id> [--yes]
docbox engines list
docbox engines remove <engine> [--yes]
docbox read <file|dir>... --model <id> [--format txt|md|json|pdf] [--out DIR] [--recursive]
docbox settings show
docbox settings set default-model <id|none>
docbox settings set cloud on|off
docbox bench ...        (section 2)
docbox mcp ...          (section 3)
```

- Exit codes: `0` ok, `1` error, `2` usage, `3` needs an external program (Tesseract/Ollama),
  `4` blocked (doesn't fit, cloud switched off).
- `--json`: results on stdout; errors as `{"error": {"code", "detail"}}` on stderr.
- Destructive commands ask for confirmation unless `--yes`; with no TTY and no `--yes` they
  refuse instead of hanging.
- `docbox read` records the read in history, so it shows under Recent files in the app.

### Shared data with the desktop app

- `paths.get_data_dir()`: `DOCBOX_DATA_DIR` → the desktop app's folder if it exists
  (`io.github.docboxai.docbox` under the OS's local data dir) → the platformdirs fallback.
  Settings already live in the user config dir, shared by both.
- Engine packages are per-environment. `core/runtime.py` gains a `tool` mode for a
  standalone install: `uv pip install --python <sys.executable> "<pkg>"` constrained by a
  `constraints.txt` exported from `uv.lock` and shipped as package data.
- Two processes can now write the same files: `history.py` and `config_store.py` take a
  cross-process lock (`filelock`); a model download takes a per-model lock file, so a
  second installer reports "already being installed" instead of corrupting files.

## 2. Benchmarks  *(proposed — please review)*

```
src/docbox/benchmark/
  dataset.py   BenchItem, DatasetSource protocol, FilesSource, ManifestSource, resolve()
  metrics.py   normalize(), cer(), wer()  (rapidfuzz Levenshtein)
  worker.py    `python -m docbox.benchmark.worker`: one model, JSON lines in/out
  runner.py    run(config) -> runs models one after another, each in its own worker
  store.py     <data>/benchmarks/<run_id>/{run.json, results.jsonl, report.md, inputs/}
  report.py    leaderboard, Markdown/JSON/CSV
```

### Datasets

- **Files source**: any files and folders the user picks (`--recursive` for subfolders).
  Reference text is optional per file:
  - `invoice.gt.txt` next to `invoice.pdf` → reference for the whole document
    (pages joined by a blank line);
  - `invoice.p3.gt.txt` → reference for page 3 only (wins over the whole-file one).
- **Manifest source**: `bench.json` or `bench.jsonl`, paths relative to the manifest:
  ```json
  {"name": "Invoices", "items": [
    {"file": "a.pdf", "gt_file": "a.txt"},
    {"file": "b.png", "gt": "Total due $1,284.00"},
    {"file": "c.pdf", "pages": [{"page": 1, "gt": "..."}, {"page": 2, "gt_file": "c2.txt"}]}
  ]}
  ```
- `DatasetSource` is a protocol (`items() -> Iterator[BenchItem]`); `resolve(spec)` picks a
  source by form (paths, `*.json[l]` manifest). Public datasets later register a scheme
  (e.g. `public:funsd`) without touching the runner.

### Running

- Models run **one after another, each in a fresh worker subprocess**: honest peak memory
  per model (sampled with psutil), a crash or hang only fails that model, RAM is freed
  between models, and no native libraries stay loaded in the parent (Windows file locks).
- The worker loads the engine once (timed separately as *load time*), then reads every
  page and streams one JSON line per page: text, lines with confidences, seconds.
- Per-page timeout (default 300 s); a timed-out or crashed worker marks the remaining pages
  of that model as failed and the run moves on.
- Model selection: explicit ids, or `--all-ready` (every installed model that can run;
  cloud models only if the cloud switch is on). Models that aren't installed are skipped
  with a reason, or installed first with `--install-missing`.
- Runs are cancellable; runs left `running` when their process died are marked
  interrupted (same as read history).

### Metrics

- Normalisation before scoring: Unicode NFKC, collapse runs of whitespace, trim;
  `--ignore-case` optional.
- **CER** = character edit distance / reference length; **WER** = the same over
  whitespace-separated words. Aggregated per model over all scored pages, weighted by
  reference length (micro-average). Accuracy shown as `1 − CER`.
- Always: pages read, pages failed, load time, mean and median seconds per page, peak
  memory (MB), mean line confidence (when the engine reports it).
- Ranking: by CER when references exist, otherwise by seconds per page.

### CLI

```
docbox bench run <paths|manifest>... [--models a,b | --all-ready] [--name NAME]
                 [--recursive] [--install-missing] [--ignore-case] [--json]
docbox bench list
docbox bench show <run_id>              leaderboard + per-file summary
docbox bench report <run_id> [--format md|json|csv]
docbox bench cancel <run_id>
docbox bench delete <run_id> [--yes]
```

### HTTP (for the app)

`POST /api/benchmarks` (multipart files + optional `.gt.txt` files + model ids + name; the
uploads are stored in the run's `inputs/` so it can be re-run), `GET /api/benchmarks`,
`GET /api/benchmarks/{id}`, `GET /api/benchmarks/{id}/pages/{item}/{page}` (per-model text
of one page plus the reference, for Compare), `GET /api/benchmarks/{id}/pages/{item}/{page}/image`,
`POST /api/benchmarks/{id}/cancel`, `POST /api/benchmarks/{id}/rerun`, `DELETE /api/benchmarks/{id}`.
Runs started by the CLI or MCP reference files by path instead of copying them.

## 3. MCP server  *(proposed — please review)*

- `docbox mcp` runs a stdio MCP server built with the official `mcp` Python SDK
  (FastMCP). Agents configure it as `uvx docbox mcp` (or `docbox mcp` when installed);
  `docbox mcp config [claude|cursor|vscode]` prints the snippet to paste.
- Tools are thin wrappers over `service` and `benchmark`, with structured (Pydantic)
  outputs and MCP tool annotations (`readOnlyHint`, `destructiveHint`) so clients can ask
  the user before removals:

| Tool | Notes |
|---|---|
| `get_device` | read-only |
| `list_models(status?, fits_only?)`, `get_model(id)` | read-only |
| `install_model(id)` | background job; returns `job_id`; progress via `get_install_status` |
| `get_install_status(job_id)` | read-only |
| `remove_model(id)`, `remove_engine(engine)` | destructive |
| `read_file(path, model_id, format?)` | returns the text and per-page lines; saves output like the app |
| `get_settings`, `update_settings(...)` | |
| `start_benchmark(paths, models?, all_ready?, name?, recursive?, install_missing?)` | returns `run_id` immediately |
| `get_benchmark(run_id)` | status, progress, leaderboard |
| `get_benchmark_page(run_id, item, page)` | every model's text + the reference, for comparing |
| `list_benchmarks`, `cancel_benchmark`, `delete_benchmark` | |

- Long work (installs, benchmarks) never blocks a tool call: it runs on a background thread
  in the server process and the agent polls; progress notifications are sent when the
  client supports them. Benchmark workers are subprocesses either way.
- Resources: `docbox://benchmarks/{run_id}/report` (Markdown report).
- `docs/agents.md`: setup per client, and the recommended agent workflow
  (device → list models → install what fits → start benchmark → poll → report → set default).

## 4. Benchmarks view in the app  *(proposed — please review)*

Built from the design's landing frames ("The local OCR test bench", Batches, Compare) with
the app's existing shell, tokens and `ui.tsx` building blocks. A new nav pill,
**Benchmarks**, after Read a file.

- **New benchmark** panel: drop files or a folder (`webkitdirectory`), reference texts are
  picked up from `.gt.txt` files in the same drop; model checklist (all ready models
  preselected, fit chips, cloud models only when the switch is on); name; **Start**.
- **Batches**: one card per run (CLI/MCP runs included) — name, pages, models, status with
  live progress, best read % and seconds per page; open, re-run, delete.
- **Run detail**:
  - Leaderboard table: model, accuracy (1 − CER), WER, s/page, load time, peak RAM,
    confidence; best value per column highlighted; **Set as default** on each row.
  - **Compare** card (as in the design): the page image beside every model's reading,
    differences from the reference highlighted as "slips" with a count per model;
    reference = the ground truth if given, otherwise a model the user picks. Page picker
    across all files.

## Testing

- Existing backend suite passes unchanged after the service refactor.
- `tests/service/`, `tests/cli/` (CLI run in-process via `main(argv)`, `--json` output and
  exit codes, temp `DOCBOX_DATA_DIR`).
- `tests/benchmark/`: dataset resolution (sidecars, per-page sidecars, manifests), metrics
  against hand-computed values, runner with a fake engine model registered for tests
  (worker subprocess path included), store and interrupted-run handling.
- `tests/mcp/`: in-memory MCP client session lists tools and calls each against the fake
  engine.
- Frontend: `tsc` and `npm run build`; the view is checked in a browser against the dev
  backend.

## Build order

1. Service layer + CLI (+ data-dir sharing, file locks, `tool` runtime mode).
2. Benchmark package + `docbox bench`.
3. MCP server + `docs/agents.md`.
4. Benchmark HTTP routes + Benchmarks view.
