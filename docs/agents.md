# Using DocBox from AI agents

DocBox gives agents (Claude Code, Claude Desktop, Cursor, VS Code, or anything that speaks
MCP) the same abilities as the app: check the computer, install OCR models, read files,
and benchmark models on the user's own documents. Two ways in:

- **MCP server**: `docbox mcp` serves the tools below over stdio. Best for chat agents.
- **CLI**: every `docbox` command takes `--json` and has stable exit codes. Best for
  agents that run shell commands, scripts and CI.

Both run the OCR engines on this computer and share the desktop app's models, settings,
Recent files and benchmark runs when the app is installed.

## Install

```sh
uv tool install git+https://github.com/docboxai/docbox-app   # puts `docbox` on PATH
docbox device                                                # check it works
```

From a checkout instead: `uv sync --extra paddle`, then `uv run docbox ...`.

## Connect an MCP client

`docbox mcp config <client>` prints the exact setup for this computer:

```sh
docbox mcp config claude-code     # prints: claude mcp add docbox -- /path/to/docbox mcp
docbox mcp config claude-desktop  # JSON for claude_desktop_config.json
docbox mcp config cursor          # JSON for ~/.cursor/mcp.json
docbox mcp config vscode          # JSON for .vscode/mcp.json
```

Without installing: `{"command": "uvx", "args": ["--from", "git+https://github.com/docboxai/docbox-app", "docbox", "mcp"]}`.

## Tools

| Tool | What it does |
|---|---|
| `get_device` | Memory, processor, disk, GPU, data folder |
| `list_models(status?, fits_only?)` | Every model: installed or not (`status`), whether it fits (`fit`), the recommended one |
| `get_model(model_id)` | One model |
| `install_model(model_id)` | Starts installing (engine packages, then weights); returns a job |
| `get_install_status(job_id)` | Poll until `done` / `error` |
| `remove_model(model_id)` | Deletes a model's files (destructive) |
| `list_engines` / `remove_engine(engine)` | Engine packages and their disk use / uninstall (destructive) |
| `read_file(path, model_id?, format?, include_lines?, use_pdf_text?, max_chars?)` | Reads a file of up to 5 pages, saves the text like the app, returns it (at most `max_chars`; `next_page` says where `get_read` continues) |
| `start_read(path, model_id?, format?, use_pdf_text?)` | Starts reading a file of any length in the background; returns its `read_id` at once |
| `get_read(read_id, from_page?, max_chars?, include_lines?)` | Poll until `done` / `error`; then its text, whole pages from `from_page` while they fit in `max_chars` |
| `get_settings` / `update_settings(default_model_id?, cloud_enabled?)` | Default model, cloud switch |
| `start_benchmark(paths, models?, name?, recursive?, install_missing?, ignore_case?)` | Starts a benchmark; returns its id at once |
| `get_benchmark(run_id)` | State, progress and the live leaderboard |
| `get_benchmark_page(run_id, file_id, page?, against?)` | Every model's reading of one page, mistakes marked |
| `list_benchmarks` / `cancel_benchmark` / `delete_benchmark` | Saved runs |
| resource `docbox://benchmarks/{run_id}/report` | The run's report, Markdown |

PDF pages that already carry their own text (an exported invoice, a report saved from a
word processor) use that text instead of OCR; pass `use_pdf_text=false` to read every page
with the model. Each page in a result says which it was (`source`: `ocr` or `pdf_text`).

Errors come back as tool errors whose text starts with a code: `not_found`, `invalid`,
`conflict`, `needs_prerequisite` (the user must install Tesseract or Ollama), `blocked`
(cloud engine off), `unavailable`, `failed`.

## Workflow: which model reads these documents best?

1. `get_device`, then `list_models(fits_only=true)`.
2. Install the candidates that aren't installed: `install_model`, poll `get_install_status`.
3. `start_benchmark(paths=["/path/to/folder"], models=[...])`.
4. Poll `get_benchmark` (every few seconds) until `state` is `done`. The leaderboard in
   `summary` is ranked by accuracy when reference text exists, else by speed; each row
   also has seconds per page, load time, peak memory and confidence.
5. Look at the hard pages with `get_benchmark_page`.
6. Offer `update_settings(default_model_id=...)` for the winner.

Reference text makes the ranking meaningful. Put it next to each document (`invoice.gt.txt`
for the whole document, `invoice.p2.gt.txt` for page 2) or in a manifest:

```json
{"name": "Invoices", "items": [
  {"file": "a.pdf", "gt_file": "a.txt"},
  {"file": "b.png", "gt": "Total due $1,284.00"},
  {"file": "c.pdf", "pages": [{"page": 2, "gt": "..."}]}
]}
```

An agent can also make reference text: read a few files with the most accurate model,
have the user correct them, save them as `.gt.txt`, then benchmark the faster models.

## The same from the CLI

```sh
docbox --json models list --fits
docbox models install paddleocr-mobile-en
docbox --json bench run ./invoices --models paddleocr-mobile-en,tesseract-eng
docbox --json bench page <run-id> invoice.pdf 2
docbox bench report <run-id> --format md
```

Exit codes: `0` ok, `1` error, `2` usage, `3` needs Tesseract or Ollama, `4` blocked. With
`--json`, errors are `{"error": {"code", "detail"}}` on stderr. Commands that delete things
need `--yes` when there's no terminal to ask.
