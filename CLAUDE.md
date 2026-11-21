# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

DocBox is a native desktop app (Windows, macOS on Apple Silicon, Linux) for discovering, downloading, and
running open-source OCR models locally — no login, no cloud calls by default. It checks
device RAM/CPU/disk against each model's requirements before recommending it.

Three-part architecture, distributed as installers via GitHub Releases:

- **Desktop app**: a native Rust window drawn by GPUI with gpui-kit's components
  (`desktop/`). No webview: the views are Rust (`desktop/src/views/`).
- **Backend**: a local FastAPI + uvicorn server (`src/docbox/backend/`), spawned by the
  desktop app as a child process (a venv's `python -m docbox.backend.main`) and stopped
  with its whole process tree on exit; it also exits by itself if the app dies first
  (see "Child processes never outlive the app"). The app talks to it over
  `http://127.0.0.1:<port>` (`desktop/src/api.rs`); the window shows the setup screen
  until `desktop/src/backend.rs` reports it ready.
- **Models**: registered against a `ModelSpec`/`OCREngine` abstraction
  (`src/docbox/backend/core/registry.py`, `src/docbox/backend/engines/`), stored under
  the data dir from `core/paths.py` (`DOCBOX_DATA_DIR`, else platformdirs' user *data*
  dir; never the cache dir).

See "Packaging and the managed runtime" below for how installed builds get Python.

## Commands

### Setup

```sh
uv python pin 3.12      # already pinned via .python-version
uv sync --extra paddle  # base deps + PaddleOCR; add --extra easyocr for EasyOCR/PyTorch
# (not --all-extras: the -gpu extras conflict with the CPU ones, see "graphics card" below)
```

On Linux, GPUI needs the Vulkan, Wayland, xkbcommon and fontconfig development packages
(the `desktop` job in `.github/workflows/ci.yml` lists them for Ubuntu).

### Run the full app

```sh
cargo run --manifest-path desktop/Cargo.toml
```

Debug builds run the repo's `.venv/…/python`, so `uv sync` must have been run first. A plain
`uv sync` is exact: it uninstalls extras you didn't pass, so always pass the extras you
need. Quit an installed DocBox first: it uses the same data folder, so the single-instance
check hands the dev build's launch to it. The first build compiles GPUI (about 25 minutes
at `-j 2` on a small machine).

For a test run, give it a throwaway data folder **and settings folder**: settings live in
the user's config dir (`core/config_store.py`, platformdirs), not `DOCBOX_DATA_DIR`:
`DOCBOX_DATA_DIR=/tmp/d XDG_CONFIG_HOME=/tmp/d/config cargo run --manifest-path desktop/Cargo.toml`
(Linux; `HOME` on macOS; Windows has no override). The default output folder is still
`Documents/DocBox` unless that settings file says otherwise.

### Build an installer locally

```sh
scripts/desktop_uv_sidecar.sh          # copies your uv to desktop/binaries/uv-<target-triple>
cargo install cargo-packager --locked  # once
cd desktop && cargo packager --release # installers in desktop/target/release/packages
```

`desktop/Packager.toml` lists the formats, the bundled `backend/` resources and the bundled
`uv`; release CI downloads a pinned, checksum-verified uv instead of copying yours.

### Backend only

```sh
uv run python -m docbox.backend.main --port 8756
```

Swagger UI at `http://127.0.0.1:8756/docs`. Useful for iterating on routes without
rebuilding the desktop app.

### CLI (`docbox`)

```sh
uv tool install "docbox[agents] @ git+https://github.com/docboxai/docbox-app"   # standalone, with `docbox mcp`
uv run docbox --help
uv run docbox models list --json
uv run docbox read invoice.pdf --model paddleocr-mobile-en --format md
```

### Tests and lint

```sh
uv run pytest                                          # full backend suite
uv run pytest tests/backend/test_models_routes.py       # one file
uv run pytest tests/backend/test_platforms.py::test_ollama_status_unavailable_when_not_running  # one test
uv run ruff check src/docbox                             # lint (line-length 100)
```

Backend routes are tested directly via `fastapi.testclient.TestClient(create_app())` —
no subprocess needed. Tests that depend on environment state (`tesseract` on PATH,
`easyocr` importable, Ollama running, an NVIDIA key set) use `pytest.skip`/fixtures rather
than mocking those dependencies away — see `tests/backend/test_models_catalog.py` for the
pattern.

Every test runs with its own temp `DOCBOX_DATA_DIR` (autouse `_isolated_data_dir` in
`tests/conftest.py`), so the suite never touches the real data folder (the installed
app's, or platformdirs'). Tests that need a model you downloaded by hand are marked
`@pytest.mark.real_data_dir` and use your real folder only when you ask:
`DOCBOX_TEST_REAL_DATA=1 uv run pytest` (e.g.
`tests/backend/test_models_routes.py::test_download_already_downloaded_model_reaches_done`).

The desktop app's tests: `cargo test --manifest-path desktop/Cargo.toml`. Besides unit
tests, `desktop/src/contract_test.rs` starts the real backend from `.venv` with the suite's
fake models (`tests/bench_fakes.py`), deserializes every route the app uses, and reads a
file and runs a benchmark over HTTP; it skips without a `.venv` and doesn't run on Windows
(it couldn't keep the backend off the real settings there). Change a schema in
`schemas.py` and this is the test that tells you `api.rs` needs the same change.

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
- Figures: `approx_ram_mb` is the peak while reading a page (`ram_measured` when measured,
  as `models_catalog.py`'s docstring describes), sizes and CPU/GPU speedups come from the
  model's published tables (`figures_source`, which must be on the opener allow-list).
  `preferred_device` ("gpu" when a graphics card makes it several times faster) and
  `inference_device()` give `ModelInfo.device`: where it reads here and what would be
  faster (see "Reading on a graphics card" below).

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
`.python-version` as resources (`backend/`, `desktop/Packager.toml`) and `uv` next to
the program (`external-binaries`). `desktop/src/backend.rs::resource_dir` finds `backend/`
where each installer puts it: beside the program on Windows, `Contents/Resources` on macOS,
`lib/<program>` beside `bin/` on Linux. On launch `backend.rs::ensure_runtime` runs
`uv sync --frozen --no-dev --no-install-project` into
`<app_local_data_dir>/runtime/.venv` (managed CPython via `UV_PYTHON_PREFERENCE=only-managed`),
skipped when the venv exists and `runtime/uv.lock.installed` matches the bundled lock.
The backend then runs with `PYTHONPATH=<resources>/backend/src` (the project is never
installed: its dir is read-only under Program Files), `DOCBOX_RUNTIME_MODE=managed`,
`DOCBOX_UV`, `DOCBOX_DATA_DIR`, `PYTHONPYCACHEPREFIX=<data>/runtime/pycache` (bytecode
written next to the bundled source would outlive the uninstaller), and the same `UV_*`
env vars. Logs go to
`<data>/logs/{setup,backend}.log`. When uv or the backend ends before it's ready, the app
adds how it ended (exit status, or the signal of a crash, which prints nothing itself) to
that log and to the error screen.

HTTPS trusts the operating system's certificates, so downloads work behind company proxies
that inspect HTTPS with their own CA: every uv the app runs gets `UV_SYSTEM_CERTS=1`
(`backend.rs::uv_env`), and each Python entry point (`create_app()`, the CLI's `main()`, the
benchmark worker) calls `core/tls.py::use_system_certificates()`, which injects
`truststore` into `ssl`, urllib3 and requests.

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

#### Reading on a graphics card

PaddleOCR (and PaddleOCR-VL) and EasyOCR also have a graphics-card build: the `paddle-gpu`
and `easyocr-gpu` extras, CUDA 12.6 (`paddlepaddle-gpu` from Paddle's own index, torch from
PyTorch's cu126 index; Windows and Linux x86_64 only, empty elsewhere). Each conflicts with
its CPU extra (same modules) and with the other (on Linux Paddle pins NCCL 2.25.1 exactly,
every torch cu126 build another), declared in `[tool.uv] conflicts`: one engine at a time
uses the card, and `--all-extras` no longer works. Paddle's Windows wheel ships no CUDA
DLLs, so the extra adds NVIDIA's runtime wheels there and `engines/cuda.py` puts their
`bin` dirs on the DLL search path before Paddle loads. `runtime.switch_build` installs one
build in place of the other with an exact sync (tool mode: uninstall the swapped dists,
then `uv pip install` with `pins/constraints-<extra>.txt`), deferred to a restart like a
removal when the engine is loaded; `installed_extras()` still names the engine, `build_of()`
says which build, and state.json's `extras` (`synced_extras()`) names the build so
`ensure_runtime` re-syncs the right one. It's a 2–4 GB Python package install
(`runtime.GPU_DOWNLOAD_MB`, measured from uv.lock), so it only happens when the user picks
it (Device view, `docbox engines build`, MCP `switch_engine_build`), never on its own.

`core/gpu.py` decides where each model reads: `support()` (an NVIDIA card via nvidia-smi in
`core/device.py`, driver CUDA ≥ 12.6, compute capability 6.0–9.x: no RTX 50 series on the
cu126 builds), the engine's build, the settings (`device_preference` auto/cpu/gpu, auto
meaning models whose `preferred_device` is "gpu"; per-model `model_devices` win), and free
graphics memory (`approx_ram_mb` as the estimate). `choose()` is pure and tested case by
case. `gpu.load(spec, engine)` (engine_cache and the benchmark worker) calls the engine's
`use_device()` before `load()`; if loading on the card raises, it loads on the CPU and
`record_fallback` keeps why (shown as the model's note until a settings or build change
clears it). The engines also fall back when the card fails on the first page or runs out of
memory on any page. Changing the device settings evicts loaded engines. Never run a real
model on the GPU in tests: they fake engines, nvidia-smi and uv (`tests/backend/test_gpu.py`).

Releases: `.github/workflows/release.yml` on `v*` tags. Its `check` job refuses a tag on a
commit that isn't on `main` or a version that doesn't match `desktop/Packager.toml`,
`desktop/Cargo.toml` and `pyproject.toml`. Each platform's `build` job runs
`cargo packager --release` (cargo-packager pinned to an exact version) and uploads its
installers: NSIS and MSI, the macOS .dmg and .app.tar.gz, AppImage and .deb (no .rpm). The
`release` job names them `DocBox-<version>-<os>-<arch>.<ext>` and creates a draft release,
failing if an installer is missing or unexpected. Its third-party actions are pinned to
commits. Linux bundles uv's glibc build: the AppImage step adds a library path (`RUNPATH`)
to every program in `usr/bin`, which makes the static musl build crash on start. The Linux
`build` job runs the uv inside the AppImage and the .deb (`scripts/check_bundled_uv.sh`)
before uploading them.

Builds are signed for the in-app updater with the minisign key in the
`TAURI_SIGNING_PRIVATE_KEY*` secrets (named for the shell that came first; cargo-packager
reads the same key format), and the release job writes two manifests pointing at the
renamed files: `updates.json` for this app's updater (`desktop/src/update.rs`,
cargo-packager-updater: `<os>-<arch>` with a `format`) and `latest.json` for copies from
before it (0.1.x, Tauri's updater: `<os>-<arch>[-<installer>]`). Every installed copy back
to 0.1.0 only accepts that key (`update.rs::PUBKEY`). `update.rs` installs a signed update
in-app where a copy can replace itself (the Windows installer, the macOS app, an AppImage;
it stops the backend first), and otherwise, or when there's no usable manifest or the
install fails, compares the version with GitHub's latest release and links to the releases
page. A .deb never updates itself: its program belongs to the package manager.

External web pages open only through `desktop/src/links.rs::open`, which refuses anything
but an `https` address; the app's own links are constants there, and
`tests/backend/test_external_links.py` checks those and every address the backend hands it
(prerequisite download pages, `ocrbench.json`, models' `figures_source`).

Uninstalling leaves the choice to the user. On Windows, the NSIS uninstaller asks whether to
delete the data too (a box, unticked by default; silent uninstalls and updates never delete
it): `nsis.appdata-paths` in `desktop/Packager.toml` names the app's data folder and the
CLI's fallback one (`%LOCALAPPDATA%\docbox\DocBox`). The MSI and the macOS and Linux
packages never delete data; the wiki's Troubleshooting page says where it is. Results in
`Documents/DocBox` are never deleted.

Child processes (the bootstrap `uv`, the backend) go through `outside_appimage` in
`backend.rs`: the AppImage launcher's PYTHONHOME/PYTHONPATH/LD_LIBRARY_PATH point into its
mount and would break the managed Python.

### Child processes never outlive the app

- **Port:** the app starts the backend with `--port 0`: the backend binds a free port
  itself, prints `{"docbox_backend": {"port": N}}` as its first stdout line and then points
  fd 1 at stderr (`backend.log`). `backend.rs::port_report` waits for that line (anything else
  on stdout goes to the log), then polls `/api/health`; if either doesn't come, boot fails
  with the end of `backend.log`. Run by hand, the backend still defaults to port 8756, which
  Docker uses.
- **Lifeline:** the app starts the backend with `--exit-on-stdin-close` and a piped stdin
  it never writes to (`backend.rs`, `Processes::lifeline`). When that pipe closes (the app
  drops it on exit, or the OS closes it because the app crashed or was force-quit), the backend stops
  its own children (`stop_children`: engine installs, benchmark workers), asks uvicorn to
  shut down, and hard-exits after a few seconds if that hangs. A backend run by hand or in
  Docker has no flag and ignores stdin.
  Wait for EOF with `core/lifeline.py`, never a blocking read: on Windows a pending read on
  the stdin pipe makes DLLs that touch the standard handles as they load (numpy, so Paddle
  and torch) hang the import for ever. It polls with `PeekNamedPipe` there.
- **Process groups:** on Unix the backend and the bootstrap `uv` each lead their own process
  group, so `stop_child`/`kill_tree` SIGTERM the whole group and SIGKILL what's left after a
  grace period. Windows uses `taskkill /T /F`, which also reaches past the venv's
  `python.exe` launcher.
- **Benchmark workers:** they get the same kind of lifeline from whoever runs the benchmark
  (the app's backend, the CLI, the MCP server). See Benchmarks below.
- **One instance:** `desktop/src/instance.rs`, first thing in `main`: the running app holds
  an exclusive lock on `<data>/instance.lock` (the OS drops it when the process ends, crash
  or not) and listens on a loopback port written to `<data>/instance.port`. A second launch
  that can't take the lock sends that port a token and exits; the first brings its window
  to the front. So there's never a second backend or first-run `uv sync` on the same data.
  Closing the window (the title bar's button on Linux, the system one elsewhere) and
  quitting both go through `Backend::shutdown`.

### The service layer: one implementation behind the app, the CLI and MCP

`src/docbox/service/` holds the operations (models, engines, device, settings, reading
files) as plain functions with no FastAPI imports. The HTTP routes (`backend/api/`), the
`docbox` CLI (`src/docbox/cli/`, argparse) and the MCP server are thin front ends over it.
Failures are `service.errors.ServiceError` subclasses: routes map `.status` to an HTTP code
via `api/errors.py::http_errors()`, the CLI maps them to exit codes (`cli/output.py`: 3 needs
an external program, 4 blocked) and `{"error": {"code", "detail"}}` on stderr with `--json`.
Put new behaviour in `service/`, not in a route, so every front end gets it.

The CLI runs engines in-process and shares the desktop app's data dir: `paths.get_data_dir()`
is `DOCBOX_DATA_DIR`, else the app's folder (`io.github.docboxai.docbox`, the per-user local
data folder the desktop app uses, `backend.rs::data_dir`, where the earlier Tauri shell
kept it too) when it exists, else platformdirs'. Because several processes can now
write it, read history and settings take cross-process file locks (`core/locks.py`,
`filelock`), and installing a model holds a per-model lock (a second process gets
`Conflict`; removing an engine takes all of its models' locks). Each read records its
process (`ReadSummary.pid`), so app startup only marks reads of dead processes as failed.
`runtime/state.json` belongs to the installed app's managed env: only `managed` mode reads
or writes it. `docbox` (`run()`) moves fd 1 to stderr under `--json` and writes the result
to a private copy, because engines running in-process print to stdout. `core/runtime.py` has a third mode, `tool` (a standalone `uv tool install` /
pip install with no project to sync): extras go in with `uv pip install` pinned by
`core/pins/constraints.txt`, exported from `uv.lock` by `scripts/export_pins.sh`; rerun it
whenever `uv.lock` changes (`tests/service/test_shared_state.py` fails when it's stale).

Tests: `tests/conftest.py` gives every test a temp `DOCBOX_DATA_DIR` (`data_dir` returns it) and `fake_model` /
`installed_fake` (a registered `test-fake` model that reads instantly), and the CLI is run
in-process with `docbox.cli.main.main(argv)`.

### Benchmarks (`src/docbox/benchmark/`)

`runner.create()` checks the dataset (`dataset.py`: files/folders with `.gt.txt` /
`.pN.gt.txt` sidecars, or a `.json`/`.jsonl` manifest) and models up front and saves a
queued run; `runner.execute()` then runs each model **in its own worker process**
(`python -m docbox.benchmark.worker`; the JSON job is one line on stdin, which the runner
keeps open as a lifeline, so a worker exits when whoever started it is gone; one JSON
event per line on a private copy of stdout; libraries' own prints are moved to stderr) — for honest peak memory
(psutil, sampled by the parent), crash/hang isolation (per-page timeout) and so native libs
never load in the backend. Runs live in `<data>/benchmarks/<run_id>/` (`store.py`); only the
running process writes them, a `cancel` file stops them from any process, and a running run
whose pid is gone reads as `interrupted`. `report.py` builds the leaderboard (CER/WER via
rapidfuzz on NFKC/whitespace-normalised text, failed pages scored as empty) and the per-page
compare view with diff spans ("slips"). `service/benchmarks.py` is the front-end API.
Tests use fake engines in `tests/benchmark/bench_fakes.py`, loaded into workers through
`DOCBOX_PRELOAD`.

### MCP server (`src/docbox/mcp_server.py`)

`docbox mcp` serves an MCP server over stdio (official `mcp` SDK 2.x: `MCPServer`, not the
1.x `FastMCP`). The SDK is the `agents` extra (and in the `dev` group for tests), not a base
dependency: the desktop app's managed runtime never runs the MCP server, so it doesn't
download it. `cli/commands/mcp.py` imports `mcp_server` only when serving, and without the
SDK `docbox mcp` fails with the install command; nothing else may import `mcp`. Tools are plain sync functions over `service/` (the SDK runs them on worker
threads and diverts stray stdout writes, so a chatty OCR library can't corrupt the
protocol); `ServiceError`s become `ToolError("<code>: <detail>")`. Long work returns an id
to poll (`install_model` → `get_install_status`, `start_benchmark` → `get_benchmark`,
`start_read` → `get_read`; `read_file` refuses documents over 5 pages). Text comes back
in whole pages within `max_chars` (`next_page` continues). Mark
new tools with the right `ToolAnnotations` (`_DELETES` for anything that removes files).
`docs/agents.md` is the user-facing guide; keep it in step with the tool list.
`DOCBOX_PRELOAD` (`docbox/plugins.py`) imports extra model-registering modules in every
process (CLI, MCP server, benchmark workers); tests rely on it.

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
- **CORS** allows no website by default (the desktop app is native and sends no `Origin`);
  `DOCBOX_CORS_ORIGINS` adds origins.
- **Host check** (`TrustedHostMiddleware`): only `127.0.0.1` / `localhost`, plus
  `DOCBOX_ALLOWED_HOSTS` (the Docker engine containers set their service names). This
  stops DNS rebinding, where another site's hostname resolves to 127.0.0.1 and CORS
  never applies. Tests' `client` fixture uses `base_url="http://127.0.0.1:8756"` for it.
- **Cross-site writes**: a POST/PUT/PATCH/DELETE whose `Origin` isn't the backend's own
  is refused unless it carries `X-DocBox-Client` (`core/client_header.py`), which other
  sites can't add without a preflight they fail. Requests without `Origin` (curl,
  `RemoteEngine`) and Swagger UI at `/docs` pass. `desktop/src/api.rs` sends it.

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

PDFium (pypdfium2) isn't thread-safe and two threads in it at once crash the process, while
the reader thread, `/api/ocr/run` and MCP tools all open PDFs. Keep every PDFium call in
`core/pages.py`, holding `_PDFIUM_LOCK`, and close pages and bitmaps there rather than leaving
them to finalizers (`tests/backend/test_pdf_threads.py`).

Engines are kept loaded between reads (`core/engine_cache.py`): reads and `/api/ocr/run` take
the model's engine through `engine_cache.loaded(spec)`, which loads it once, keeps one
engine (LRU), serializes runs on it with a per-engine lock and drops it after
`DOCBOX_ENGINE_IDLE_S` (default 300 s, 0 = never). Anything that deletes model files calls
`engine_cache.evict()` first (it waits for a read in progress). The benchmark worker never
uses it: a fresh process per model keeps its load and memory numbers honest.

Reads take a PDF page's own text instead of OCRing it (`pages.iter_read_pages`,
`ReadPage.source = "pdf_text"`) when it has at least `_MIN_TEXT_CHARS` of text, isn't
rotated, and images cover at most `_MAX_IMAGE_COVER` of it (scans are OCRed again, even
with an older OCR layer). Its lines come from pdfium's text rectangles, boxed in the
rendered page's pixels so a searchable PDF lines up. The model is loaded only at the first
page that needs OCR. `use_pdf_text=False` (reads API form field, the Read a file switch,
`docbox read --ocr-all`, MCP `use_pdf_text`) OCRs every page; benchmarks always do
(`iter_pages`).

`core/config_store.py` also holds the default model, the output folder, the RAM limit and
the cloud switch (`/api/settings`). The RAM limit marks models over it as not fitting (and
never recommended), and `reader.check_memory()` refuses to start a read (or `/api/ocr/run`)
whose model takes more than the limit, or more than is free when it isn't loaded yet. With the switch off, NVIDIA NIM models are hidden and refused
(`platforms.cloud_blocked`); an unset switch follows whether a key was saved.

Downloads can be paused: `POST .../download/pause` sets a flag the job's progress callback
checks, raising `JobPaused` at the engine's next progress report (every chunk for
Tesseract/Ollama, every output line for `uv`, which is then killed; only between model
files for PaddleOCR). Starting the download again resumes it. `ModelInfo.active_job`
carries the running or paused job so the UI can rejoin it.

Tests redirect the settings file to a temp dir (`tests/backend/conftest.py`); they never
touch the developer's real NVIDIA key or settings.

### Desktop app (`desktop/`)

A Rust program drawn by GPUI, with gpui-kit's components (one dependency, `gpui-kit`; its
skills and docs at gpui-kit.com describe the API: don't guess it from older GPUI or web
examples). `main.rs` claims the single instance, starts the backend and opens the window.
`shell.rs` is the frame: the setup screen until the backend answers (`backend.rs`'s status,
polled), then the title bar, the sidebar (views and the cloud switch) and the page header
with its stat pill. `state.rs::AppState` holds the client, the current `View`, device info,
settings and a `revision` counter views observe and refetch on; `state::call` runs a
blocking `api.rs` call on the background executor and hands the result to the view.
`jobs.rs::ModelJob` is one model's download (start, poll, pause/resume, remove), kept per
model in `AppState` so progress survives switching views; `model_actions.rs` renders it as
a table cell or a full panel. `ui.rs` has the shared pieces (cards, section labels, stat
cards, chips, notices) and `format.rs` the number formats and each engine's
label/blurb/capabilities/guidance (shared by Setup and Models: add a new engine there).
Each view in `views/` is an entity: `setup`, `models`, `read` (drop, file picker, pasting
an image saves it under `<data>/pasted/`), `benchmarks` with `bench_run` (one run) and
`bench_chart` (the graph and the ranked bars), `connections`, `device`, and the shared
`prerequisite` card. `update.rs` is the updater (see Packaging), `links.rs` the only way
to open a web page, `instance.rs` the single instance.

Layout: card rows translate the web layout's `flex: 1 1 <basis>` as `flex_basis` plus grow
and shrink with `min_w_0`, never `flex_1` plus a fixed `min_w`, which can't shrink and
overflows narrow windows (tiling window managers squeeze the window below its minimum).

The Benchmarks view (`views/benchmarks.rs`: drop zone, model picker, batch cards;
`views/bench_run.rs`: leaderboard and Compare) talks to `/api/benchmarks`
(`api/routes_benchmarks.py`). Uploads are sent with their path relative to the picked folder as the multipart
file name so `.gt.txt` sidecars land next to their documents in the run's `inputs/`; the
route sanitises those paths. Runs from the CLI and MCP appear there too (same data dir). A run's leaderboard is
`BenchRunPanel::leaderboard`: one row of controls (scores from this run or OCRBench v1/v2,
the cost measure, every size or the best size of each model, a Models filter) scoping both
views below it. `bench_chart::chart` is the graph (drawn on a GPUI canvas, no chart library):
accuracy against cost on a log axis reversed so the cheapest is on the right ("most
efficient" top right), one line per family through its sizes, labelled once at its best
point. `bench_chart::bars` is the ranked bars with each row's 95% interval, and doubles as
the graph's table view. Families come from `ModelSpec.family`/`variant` (an Ollama model's
tags too), copied onto each leaderboard row by `platforms.describe()`, which never asks a
platform; `accuracy_margin` is `metrics.cer_margin()`: the ratio estimator's standard error
over the pages or documents with reference text, widened with Student's t for few of them.
"OCRBench v1/v2" plots published scores from `benchmark/ocrbench.json` (served at
`/api/benchmarks/reference`) against catalog download size, without ranking them, since
sources differ. Every score there needs a source URL and a `self_reported` flag;
`tests/benchmark/test_reference.py` checks they name catalog models. Colours
(`bench_chart::Series`): at most three series hues (validated
all-pairs for colour-blind readers) plus a neutral, by engine, never by rank; labels use
text colours, not the series hue (Tesseract's orange is under 4.5:1 as text). An engine whose
model runs in another process (Ollama, NVIDIA, `RemoteEngine`) sets `runs_in_process =
False`; the worker reports it, and the run records no peak memory, with a `memory_note`,
rather than the worker's own. The desktop app opens the report on this computer
(`POST /api/benchmarks/{id}/report/open`).

Every engine implements `delete()`; PaddleOCR's keeps model dirs another *downloaded*
catalog entry still uses (all PP-OCRv5 language families share `PP-OCRv5_server_det`).

### Website

`website/` is the landing page, separate from the app: Next.js (App Router), Tailwind 4,
Lenis smooth scrolling, bun, deployed on Vercel with `website/` as the project root. CI
lints and builds it. Its shader effects run the design's pen.dev GLSL unchanged
(`components/shader/glsl/`); `ShaderCanvas` fills the annotated uniforms and divides
gl_FragCoord by the pixel ratio so effects keep the design's pixel scale. Scroll reveals
use `data-reveal` (from `lib/reveal.ts`): put it on a wrapper, never on an element with
its own transitions, since it sets `translate` and `transition`. See `website/README.md`.

### PaddleOCR internals worth knowing before touching `engines/paddleocr_engine.py` or `paddleocr_vl_engine.py`

- Cache location is redirected via the `PADDLE_PDX_CACHE_HOME` env var, set before
  constructing the pipeline, pointed at `<data>/models/paddlex_cache` rather than
  paddlex's default (the user's home directory).
- No byte-level download progress from paddlex's downloader — progress is coarse/staged
  (detection model downloading → recognition model downloading → ready), read off
  paddlex's internal `official_models[name]` API.
- oneDNN (`enable_mkldnn=True` on the CPU; off on the graphics card) must stay on: without
  it paddle's CPU convolutions take
  about 5 GB per megapixel and tall images got the backend OOM-killed (issue #23).
  paddlepaddle 3.3 breaks oneDNN (`ConvertPirAttribute2RuntimeAttribute not support`), hence
  `paddlepaddle<3.3` in `pyproject.toml`; check oneDNN works before raising that pin.
- Paddle shrinks images whose long side is over 4000 px, so `PaddleOcrEngine.run` reads
  tall or very large images in overlapping full-resolution strips (`_strips`), each line
  kept by the strip that owns its centre; that also bounds a page's memory.
- Classic PP-OCR pipelines return `rec_texts`/`rec_scores` on the result object;
  PaddleOCR-VL instead exposes `.markdown["markdown_texts"]` via its `MarkdownMixin` —
  the two engine implementations parse results differently for this reason.
