# Agent commands, filesystem roots, budgets and the app bridge

Status: approved 2026-10-08. Follows `2026-10-07-agents-cli-benchmarks-design.md`.

## Why

PhotoCraft (github.com/storytold/photocraft) drives one command registry from its UI, CLI,
JSON control channel and MCP server; confines agent file access to roots granted at launch;
caps what one call can return; and can bridge MCP to the running desktop app over an
authenticated loopback channel. DocBox's CLI and MCP already share a service layer, but each
wires its own commands by hand, agents can't discover or batch commands, agent paths are
unrestricted, replies are unbounded, and agents can't drive the open app (whose loopback API
has no authentication). This adds those four pieces.

## 1. Command registry (`src/docbox/commands/`)

- `registry.py`: `Command(id, summary, kind, params, returns, run)`. `kind` is `read`,
  `change`, `download` or `delete` (drives MCP annotations and the change counter).
  `params` is a pydantic model with `extra="forbid"`: it validates input and is the
  command's JSON schema. Path fields are marked `ReadPath` / `WritePath`.
- `catalog.py`: every command, each a thin call into `docbox.service`: `device.info`,
  `models.list/get/install/install_status/remove`, `engines.list/remove`, `ocr.read`,
  `settings.get/update`, `bench.start/get/page/page_image/list/cancel/delete/report`.
- `executor.py`: `LocalExecutor` (runs in this process) and `BridgeExecutor` (forwards to
  the app); both `run(id, params) -> JSON` and `commands()`. `run_batch(executor, steps,
  stop_on_error)` runs up to 64 steps and returns per-step `{id, ok, result | error}`.
- MCP tools are generated from the registry: tool `models_install` for command
  `models.install`, its schema from `params`, its output schema from `returns`, its
  annotations from `kind`. Plus `command_list`, `command_run`, `command_batch`.
- CLI: `docbox commands [--filter]`, `docbox call <id> [--params JSON|@file]`,
  `docbox batch --actions steps.json [--keep-going]`. The human commands (`read`,
  `bench run`, ...) stay as they are.

## 2. Filesystem roots (`commands/paths.py`)

`docbox mcp|call|batch --read-root DIR (repeatable) --write-root DIR`. With any root given,
every `ReadPath` must resolve (symlinks followed, `~` expanded, relative paths against the
first read root) inside a read root (the write root counts as readable), and every
`WritePath` inside the write root; files found inside a folder are checked one by one.
Without roots: unrestricted, the "full control" choice from the first design. Only paths
an agent passes are checked; the app's own data dir and output folder are DocBox's.

## 3. Output budgets (`commands/budgets.py`)

- Replies: at most 1 MB of JSON; a larger reply is an error naming the limit.
- `ocr.read` text: cut at 200,000 characters with `truncated: true` and the saved
  `output_path`; page lines only on request.
- `bench.page_image`: 1024 px longest side by default, at most 2048, at most 5 MB JPEG.
- `command_batch`: at most 64 steps; it stops with a `budget` error once the replies so
  far reach 1 MB, keeping the finished steps' results.

## 4. Bridge to the running app

- The Tauri shell makes a 256-bit token per launch (`getrandom`), passes it to the backend
  as `DOCBOX_CONTROL_TOKEN` and to the webview through the `backend_token` command.
- With the token set, the backend refuses every `/api` request except `/api/health` and
  CORS preflights unless it carries `Authorization: Bearer <token>` (or `?token=` for
  `<img>`/download URLs), compared in constant time. It writes `<data>/control.json`
  (`port`, `token`, `pid`), mode 0600, at startup and removes it at shutdown. Without the
  token (Docker, `npm run dev` against a hand-started backend, tests) nothing changes.
- `POST /api/commands/{id}` runs a registry command in the backend; `GET /api/commands`
  lists them. Errors are `{"error": {"code", "detail"}}` with the usual status codes.
- `--bridge` on `mcp`/`call`/`batch`/`commands` reads `control.json`, checks the pid is
  alive and sends commands there. Roots and budgets are still applied on the agent's side.
- Change counter: a command of any kind but `read` touches `<data>/changes` (also when an
  install job finishes); `GET /api/changes` returns its stamp; the app polls it every 2 s
  and refreshes its views when it moves. So headless agents and bridged ones both show up
  in the open window.
- Trust: like PhotoCraft's, the token keeps out other users and web pages; processes
  running as the same user can read `control.json`.

## Testing

Registry/MCP parity, every command validated against its schema; roots (absolute, `..`,
symlink, folder escapes); budgets (truncation, image caps, batch limits); backend token
(refused without, accepted with, health and preflight open, control.json mode and cleanup);
the bridge end to end against a live backend with a token (`docbox call --bridge`, an MCP
stdio session with `--bridge`); and a live check in `cargo tauri dev` that the window
updates when an agent installs a model.
