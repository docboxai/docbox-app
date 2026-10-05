# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

DocBox is a native desktop app (Windows, macOS on Apple Silicon, Linux) for discovering, downloading, and
running open-source OCR models locally — no login, no cloud calls by default. It checks
device RAM/CPU/disk against each model's requirements before recommending it.

Three-part architecture, distributed as installers via GitHub Releases:

- **Frontend**: Tauri (Rust) native shell (`src-tauri/`) hosting a React + TypeScript +
  Tailwind CSS UI (`frontend/`).
- **Backend**: a local FastAPI + uvicorn server (`src/docbox/backend/`), spawned by the
  Tauri shell as a child process (a venv's `python -m docbox.backend.main`) and killed
  with its whole process tree on exit. The webview talks to it over
  `http://127.0.0.1:<port>`; the frontend polls the `backend_status` Tauri command until
  it's up, then gets the URL from `backend_base_url` (`src-tauri/src/main.rs`).
- **Models**: registered against a `ModelSpec`/`OCREngine` abstraction
  (`src/docbox/backend/core/registry.py`, `src/docbox/backend/engines/`), stored under
  the data dir from `core/paths.py` (`DOCBOX_DATA_DIR`, else platformdirs' user *data*
  dir; never the cache dir).

See "Packaging and the managed runtime" below for how installed builds get Python.

## Commands

### Setup

```sh
uv python pin 3.12      # already pinned via .python-version
uv sync --extra paddle  # base deps + PaddleOCR; --all-extras adds EasyOCR/PyTorch
npm --prefix frontend install
cargo install tauri-cli --version "^2" --locked   # once, for `cargo tauri`
```

### Run the full app

```sh
cd src-tauri && cargo tauri dev
```

`beforeDevCommand`/`beforeBuildCommand` in `src-tauri/tauri.conf.json` run relative to
the project root (the parent of `src-tauri/`), not `src-tauri/` itself — don't add a
`../` prefix to those paths. Dev builds run the repo's `.venv/…/python`, so `uv sync`
must have been run first. A plain `uv sync` is exact: it uninstalls extras you didn't
pass, so always pass the extras you need.

### Build an installer locally

```sh
cd src-tauri && cargo tauri build   # needs TAURI_SIGNING_PRIVATE_KEY (updater artifacts)
```

`build.rs` copies `uv` from PATH into `src-tauri/binaries/uv-<target-triple>` when the
sidecar is missing (gitignored); release CI downloads a pinned, checksum-verified uv
there instead.

### Backend only

```sh
uv run python -m docbox.backend.main --port 8756
```

Swagger UI at `http://127.0.0.1:8756/docs`. Useful for iterating on routes without
rebuilding the Rust shell or frontend.

### Frontend only

```sh
npm --prefix frontend run dev     # http://localhost:1420
npm --prefix frontend run build   # production build, also a good typecheck+bundle smoke test
npx tsc --noEmit                  # (run from frontend/) typecheck only
```

Outside the Tauri webview there's no `backend_base_url` command, so `frontend/src/lib/api.ts`
calls `/api` on the page's own origin and Vite's dev/preview server proxies it to
`http://127.0.0.1:8756` (override with `DOCBOX_BACKEND_URL`) — start the backend standalone
alongside it. Same-origin, so the backend's CORS allowlist doesn't apply there.

### Tests and lint

```sh
uv run pytest                                          # full backend suite
uv run pytest tests/backend/test_models_routes.py       # one file
uv run pytest tests/backend/test_platforms.py::test_ollama_status_unavailable_when_not_running  # one test
uv run ruff check src/docbox                             # lint (line-length 100)
```

Backend routes are tested directly via `fastapi.testclient.TestClient(create_app())` —
no subprocess needed. Tests that depend on environment state (a model already
downloaded, `tesseract` on PATH, `easyocr` importable, Ollama running, an NVIDIA key
set) use `pytest.skip`/fixtures rather than mocking those dependencies away — see
`tests/backend/test_models_routes.py::test_download_already_downloaded_model_reaches_done`
and `tests/backend/test_models_catalog.py` for the pattern.

There is no frontend test suite; `npm run build` / `tsc --noEmit` is the verification
step for frontend changes.

## Architecture

### The model registry is the extensibility point

`src/docbox/backend/core/registry.py` defines:

- `ModelSpec` — id, name, engine, description, languages, approx download/RAM/disk, and
  an `engine_factory: Callable[[], OCREngine]`.
- `ModelRegistry` — register/get/list, a plain in-memory dict, module-level `registry`
  singleton.
- `check_fit(spec, caps) -> FitResult` — compares a spec's requirements against
  `DeviceCapabilities` with a RAM safety margin (`_RAM_SAFETY_MARGIN_MB`).
- `recommend(specs, caps)` — Setup's "Recommended start" (`ModelInfo.recommended`): the
  highest-`quality` spec that `runs_smoothly` here, meaning the computer clears its `tier`
  (`_TIER_NEEDS`: total RAM and physical cores), `check_fit` passes and it isn't slow
  without a GPU. Quality wins over tier: a heavier model is picked only when it also
  reads better. `quality=None` (the default; language specialists, Ollama, cloud) is
  never picked, so give every new general-purpose built-in model a `tier` and `quality`.

`src/docbox/backend/engines/base.py` defines the `OCREngine` Protocol every engine
implements: `is_downloaded()`, `download(progress_cb)`, `load()`, `run(image) -> OcrResult`.

Adding a new *static* model (another PaddleOCR variant, another Tesseract language,
etc.) means adding an `OCREngine` implementation under `engines/` if it's a new engine
family, then registering `ModelSpec` entries for it in
`src/docbox/backend/models_catalog.py` (imported for its side effect in
`main.py::create_app()` — importing it is what populates the registry). No route or
schema changes are needed; `routes_models.py`/`routes_ocr.py` work generically against
whatever's registered.

**Closure trap**: `models_catalog.py` builds several specs in `for` loops (language
families, Tesseract languages). Each `engine_factory` lambda must capture the loop
variable via a default argument (`lambda det=..., rec=..., mid=...: ...`), not close
over it directly — otherwise every entry silently resolves to the last iteration's
values. `tests/backend/test_models_catalog.py::test_language_family_specs_are_distinct_not_all_the_same`
is a regression guard for this.

### Dynamic platforms sit alongside the static catalog

`src/docbox/backend/platforms/` (`ollama.py`, `nvidia_nim.py`, `__init__.py`) discovers
models from external, already-running services rather than a fixed list registered at
import time — what they have available can change any time the app isn't looking (a
user pulls an Ollama model, adds/removes an NVIDIA key), so they're queried fresh on
every request instead of cached in the `ModelRegistry` singleton.

- `platforms.list_dynamic_specs()` — called by `routes_models.list_models()` alongside
  `registry.list()`. Each platform's own lookup swallows connection/auth errors and
  returns `[]` rather than raising, so one unreachable platform never breaks the rest of
  `/api/models`.
- `platforms.resolve_spec(model_id)` — tries the static registry first, then falls
  through to the matching platform by id prefix (`ollama:`, `nvidia-nim:`). Every route
  that used to call `registry.get(model_id)` directly (`routes_models.py`,
  `routes_ocr.py`) now goes through this instead, so dynamic models work with the
  existing download-job and OCR-run machinery unchanged.

Ollama lists pulled vision models plus `RECOMMENDED_VISION_MODELS` (listed even while
Ollama isn't running, as `needs_prerequisite`); `OllamaOcrEngine.download()` pulls
through Ollama's `/api/pull` NDJSON stream and `delete()` calls `/api/delete`. Ollama
lists `name` as `name:latest`, so compare names via `normalize_model_name`. NVIDIA NIM models are cloud calls opted into via an
API key (`src/docbox/backend/core/config_store.py`, a plain local JSON file — same trust
model as `gh`'s or `aws`'s local config, not a system keychain); `is_downloaded()` on
`NvidiaNimOcrEngine` really means "is a key configured".

### Packaging and the managed runtime

Installed builds bundle the backend source + `pyproject.toml` + `uv.lock` +
`.python-version` as Tauri resources (`backend/`) and `uv` as a sidecar
(`bundle.externalBin`). On launch `main.rs::ensure_runtime` runs
`uv sync --frozen --no-dev --no-install-project` into
`<app_local_data_dir>/runtime/.venv` (managed CPython via `UV_PYTHON_PREFERENCE=only-managed`),
skipped when the venv exists and `runtime/uv.lock.installed` matches the bundled lock.
The backend then runs with `PYTHONPATH=<resources>/backend/src` (the project is never
installed: its dir is read-only under Program Files), `DOCBOX_RUNTIME_MODE=managed`,
`DOCBOX_UV`, `DOCBOX_DATA_DIR`, and the same `UV_*` env vars. Logs go to
`<data>/logs/{setup,backend}.log`.

Heavy engine packages are pyproject **extras** (`paddle`, `easyocr`; torch pinned to the
CPU index via `[tool.uv.sources]`, which only applies to *direct* deps, hence torch and
torchvision listed explicitly). `core/runtime.py` installs one on demand with
`uv sync --inexact --extra X` (inexact so it never removes another extra), and removes one
with an exact sync of the remaining extras. Native libs loaded in the running process
can't be deleted on Windows, so removal is deferred (`state.json` `resync_pending`,
applied by `ensure_runtime` at next launch) when the engine was imported this session.
`ModelSpec.requires_extra` / `.prerequisite` drive `ModelInfo.status` (`ready` /
`needs_download` / `needs_engine` / `needs_prerequisite`), and the download job installs
the extra (0–40%) before the weights (40–100%). Engine modules must import their heavy
packages lazily (inside methods): `models_catalog.py` imports every engine module even
when its extra isn't installed.

Releases: `.github/workflows/release.yml` on `v*` tags (version must match in
`tauri.conf.json`, `Cargo.toml` and `pyproject.toml`), signing updater artifacts with the
`TAURI_SIGNING_PRIVATE_KEY` secret and substituting `OWNER/REPO` in the updater endpoint.
The frontend's `UpdateBanner` calls the `prepare_restart` command (stop the backend)
before `update.install()`, because the Windows updater exits the app without the normal
close handling.

### The "never silently install untrusted binaries" rule

System-level programs (Tesseract, Ollama) are never installed without the user's
explicit action. `core/prerequisites.py` detects them (including Tesseract's default
Windows install dir, which winget doesn't add to PATH), offers a one-click
`winget install` on Windows only on a button press (Windows then shows its own UAC
prompt), and shows per-distro commands on Linux, where `sudo` is required. Python packages
(engine extras, pinned by `uv.lock`) and plain data files (model weights, Tesseract
`.traineddata`) are installed automatically. Follow the same split for new engines.

### FastAPI route handlers are sync `def`, not `async def`

Model download and OCR inference are blocking CPU-bound calls. FastAPI runs sync `def`
route handlers in a threadpool automatically, so `routes_models.py`'s download endpoint
and `routes_ocr.py`'s run endpoint stay `def` rather than `async def` — no manual
`asyncio.to_thread` needed, and uvicorn's event loop (and concurrent status polling)
isn't blocked. Download progress is polling-based (`GET .../download/status`), not SSE —
deliberate, since this is single-user localhost traffic where a ~1s poll loop is simpler
and just as robust.

The server binds `127.0.0.1`, but a web page in the user's browser can still reach
loopback, and the read history holds the text of the user's documents. `main.py` has three
guards:
- **CORS** allows only the app's own origins (Tauri's `tauri://localhost` /
  `http://tauri.localhost` and the Vite dev server on :1420), plus `DOCBOX_CORS_ORIGINS`.
- **Host check** (`TrustedHostMiddleware`): only `127.0.0.1` / `localhost`, plus
  `DOCBOX_ALLOWED_HOSTS` (the Docker engine containers set their service names). This
  stops DNS rebinding, where another site's hostname resolves to 127.0.0.1 and CORS
  never applies. Tests' `client` fixture uses `base_url="http://127.0.0.1:8756"` for it.
- **Cross-site writes**: a POST/PUT/PATCH/DELETE whose `Origin` isn't the backend's own
  is refused unless it carries `X-DocBox-Client` (`core/client_header.py`), which other
  sites can't add without a preflight they fail. Requests without `Origin` (curl,
  `RemoteEngine`) and Swagger UI at `/docs` pass. `frontend/src/lib/api.ts` sends it.

Startup work (marking unfinished reads as failed) runs in the app's lifespan, so building
an app in tests doesn't touch the real read history.

### Reading files, history and settings

`/api/reads` (`api/routes_reads.py`, `core/reader.py`) reads whole files: every page of a
PDF or multi-page TIFF (`core/pages.py`), one file at a time on a single worker thread,
then saves `.txt`/`.md`/`.json` or a searchable `.pdf` (`core/pdf_writer.py`: the page
image plus an invisible text layer in Tesseract's glyphless font) into the output folder
(`Documents/DocBox` by default). `core/history.py` keeps the index and each read's text
under `<data>/history/`; reads left unfinished when the backend stopped are marked failed
at startup. `/api/ocr/run` (one page, answered directly) stays as the contract
`RemoteEngine` speaks to engine containers. Open-file/folder actions only take a read id,
never a path. `OcrLine.box` carries line positions from engines that report them
(PaddleOCR, Tesseract, EasyOCR) so the PDF text lines up with the scan.

`core/config_store.py` also holds the default model, the output folder and the cloud
switch (`/api/settings`). With the switch off, NVIDIA NIM models are hidden and refused
(`platforms.cloud_blocked`); an unset switch follows whether a key was saved.

Downloads can be paused: `POST .../download/pause` sets a flag the job's progress callback
checks, raising `JobPaused` at the engine's next progress report (every chunk for
Tesseract/Ollama, every output line for `uv`, which is then killed; only between model
files for PaddleOCR). Starting the download again resumes it. `ModelInfo.active_job`
carries the running or paused job so the UI can rejoin it.

Tests redirect the settings file to a temp dir (`tests/backend/conftest.py`); they never
touch the developer's real NVIDIA key or settings.

### Frontend

`frontend/src/lib/api.ts` is the single typed HTTP client; every backend schema in
`schemas.py` should have a matching TS interface there. `components/Shell.tsx` is the
frame (purple hero with the top-bar pill nav, cloud switch and title),
`components/ui.tsx` holds the shared building blocks (chips, round icon actions, pill
buttons, switch, cards, tabs), and the palette and fonts (Host Grotesk headings, DM Sans body) are tokens in `styles.css`.
`lib/app.tsx` holds the current view (`ViewId`; no router library), device info,
settings and a `revision` counter views refetch on; it sits inside `BootGate`
(setup/first-run screen until the backend is ready). Per-model download state (start,
progress, pause/resume, remove) is one hook, `lib/useModelJob.ts`, rendered by
`ModelActions` (a compact table cell or the full panel); external-program setup is
`PrerequisiteCard`. In Tauri, `dragDropEnabled` is off in `tauri.conf.json` so HTML5 file
drops reach the Read a file drop zone. When adding a
new engine, add its icon/label/capabilities/guidance to the maps in
`frontend/src/lib/engineMeta.ts` (shared by Setup and Models).

Every engine implements `delete()`; PaddleOCR's keeps model dirs another *downloaded*
catalog entry still uses (all PP-OCRv5 language families share `PP-OCRv5_server_det`).

### PaddleOCR internals worth knowing before touching `engines/paddleocr_engine.py` or `paddleocr_vl_engine.py`

- Cache location is redirected via the `PADDLE_PDX_CACHE_HOME` env var, set before
  constructing the pipeline, pointed at DocBox's own `platformdirs` cache dir rather than
  paddlex's default (the user's home directory).
- No byte-level download progress from paddlex's downloader — progress is coarse/staged
  (detection model downloading → recognition model downloading → ready), read off
  paddlex's internal `official_models[name]` API.
- `enable_mkldnn=False` must be passed to the pipeline constructor — without it, CPU
  inference on this paddlepaddle 3.x build crashes with
  `NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support [...]`.
- Classic PP-OCR pipelines return `rec_texts`/`rec_scores` on the result object;
  PaddleOCR-VL instead exposes `.markdown["markdown_texts"]` via its `MarkdownMixin` —
  the two engine implementations parse results differently for this reason.
