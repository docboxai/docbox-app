"""Installs and removes engine packages (pyproject extras) in DocBox's own Python env.

The installed app ships only the base dependencies. The first time a user picks a model
from an engine family whose packages aren't present yet (Paddle, PyTorch for EasyOCR),
the download job calls `ensure_extra()`, which runs the bundled `uv` against the
bundled `uv.lock` — same pinned versions on every machine, no pip, no PyPI resolution
at runtime. Removal re-syncs without that extra, which uninstalls its packages.

Three modes:
- "managed" (installed app, `DOCBOX_RUNTIME_MODE=managed` from the Tauri shell): env
  lives in the app's data dir and the project itself isn't installed (its source is on
  PYTHONPATH), so syncs pass `--no-dev --no-install-project`.
- "tool" (a standalone `docbox` from `uv tool install` / pip): there's no project or lock
  file to sync against, so extras are installed with `uv pip install` into this Python,
  pinned by `pins/constraints.txt` (exported from uv.lock by scripts/export_pins.sh).
- "dev" (anything else: a checkout, Docker): the repo's own `.venv`; syncs keep the dev
  group and the editable project.

`state.json` (in the runtime dir) records the installed extras so the Tauri shell can
re-sync them after an app update ships a new `uv.lock`, and carries removals that had
to wait for a restart because the engine's native libraries were already loaded.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from packaging.requirements import Requirement

from docbox.backend.core.paths import get_runtime_dir
from docbox.backend.engines.base import ProgressCallback

# extra name -> (human label, a top-level module that exists iff the extra is installed)
EXTRAS: dict[str, tuple[str, str]] = {
    "paddle": ("PaddleOCR engine", "paddleocr"),
    "easyocr": ("EasyOCR engine (PyTorch)", "easyocr"),
}

# Native-extension modules that, once imported, keep DLLs/.so files open — on Windows
# those files can't be deleted until the process exits.
_LOADED_ROOTS: dict[str, tuple[str, ...]] = {
    "paddle": ("paddle", "paddleocr", "paddlex"),
    "easyocr": ("torch", "easyocr"),
}

# Top-level distributions each extra pulls in directly (mirrors pyproject.toml).
_EXTRA_ROOT_DISTS: dict[str, tuple[str, ...]] = {
    "paddle": ("paddleocr", "paddlepaddle"),
    "easyocr": ("easyocr", "torch", "torchvision"),
}


class EngineInstallError(RuntimeError):
    pass


class RemovalNeedsRestart(RuntimeError):
    """Packages are in use by this process; removal happens on next launch (managed) or
    needs a manual backend restart first (dev)."""


def project_dir() -> Path:
    override = os.environ.get("DOCBOX_PROJECT_DIR")
    if override:
        return Path(override)
    # src/docbox/backend/core/runtime.py -> project root (repo, bundled resources, /app)
    return Path(__file__).resolve().parents[4]


def _uv() -> str | None:
    return os.environ.get("DOCBOX_UV") or shutil.which("uv")


def _managed() -> bool:
    return os.environ.get("DOCBOX_RUNTIME_MODE") == "managed"


_PINS = Path(__file__).resolve().parent / "pins"
# PyTorch's CPU-only wheels (the `+cpu` pins); mirrors [[tool.uv.index]] in pyproject.toml.
_TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def _has_project() -> bool:
    root = project_dir()
    return (root / "pyproject.toml").exists() and (root / "uv.lock").exists()


def mode() -> str:
    """"managed", "tool" or "dev" (see the module docstring)."""
    explicit = os.environ.get("DOCBOX_RUNTIME_MODE")
    if explicit in ("managed", "tool", "dev"):
        return explicit
    return "dev" if _has_project() else "tool"


def can_install() -> bool:
    if not _uv():
        return False
    if mode() == "tool":
        return (_PINS / "constraints.txt").exists()
    return _has_project()


def installed_extras() -> set[str]:
    importlib.invalidate_caches()
    return {
        name for name, (_label, marker) in EXTRAS.items()
        if importlib.util.find_spec(marker) is not None
    }


def extra_installed(name: str) -> bool:
    return name in installed_extras()


def _state_path() -> Path:
    return get_runtime_dir() / "state.json"


def read_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(**updates) -> None:
    state = read_state()
    state.update(updates)
    path = _state_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)


def sync_command(extras: Iterable[str], *, inexact: bool) -> list[str]:
    cmd = [_uv() or "uv", "sync", "--frozen", "--project", str(project_dir())]
    if _managed():
        cmd += ["--no-dev", "--no-install-project"]
    if inexact:
        cmd.append("--inexact")
    for extra in sorted(extras):
        cmd += ["--extra", extra]
    return cmd


def _extra_requirements(name: str) -> list[str]:
    """The requirements the installed `docbox` distribution declares for one extra."""
    try:
        declared = importlib.metadata.requires("docbox") or []
    except importlib.metadata.PackageNotFoundError:
        return []
    reqs = []
    for req_str in declared:
        req = Requirement(req_str)
        if req.marker is not None and req.marker.evaluate({"extra": name}) \
                and not req.marker.evaluate({"extra": ""}):
            req.marker = None
            reqs.append(str(req))
    return reqs


def pip_install_command(name: str) -> list[str]:
    """Tool mode: install one extra's packages into this Python at uv.lock's versions."""
    reqs = _extra_requirements(name)
    if not reqs:
        raise EngineInstallError(f"This docbox install doesn't declare the '{name}' extra")
    return [
        _uv() or "uv", "pip", "install", "--python", sys.executable,
        "--constraints", str(_PINS / "constraints.txt"),
        "--overrides", str(_PINS / "overrides.txt"),
        "--extra-index-url", _TORCH_CPU_INDEX, "--index-strategy", "unsafe-best-match",
        *reqs,
    ]


def run_streaming(
    cmd: list[str], progress_cb: ProgressCallback, *, failure: str = "Package install failed"
) -> None:
    """Run `cmd`, turning each output line into a progress message. Neither uv nor winget
    reports an overall percentage, so progress creeps toward 95% as lines arrive."""
    progress_cb(1.0, "preparing")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    tail: list[str] = []
    steps = 0
    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            tail = (tail + [line])[-30:]
            steps += 1
            progress_cb(min(95.0, 100.0 * (1 - 0.93**steps)), line[:160])
    except BaseException:
        # The callback raises to pause the job: stop the install rather than leave it
        # running unattended. uv sync is idempotent, so the next run picks up from here.
        proc.kill()
        proc.wait()
        raise
    if proc.wait() != 0:
        raise EngineInstallError(f"{failure}:\n" + "\n".join(tail))


def ensure_extra(name: str, progress_cb: ProgressCallback) -> None:
    if name not in EXTRAS:
        raise EngineInstallError(f"Unknown engine package set: {name}")
    if extra_installed(name):
        progress_cb(100.0, "already installed")
        return
    if not can_install():
        raise EngineInstallError(
            f"The {EXTRAS[name][0]} isn't installed and DocBox can't install it here "
            f"(no `uv` available). Install uv (https://docs.astral.sh/uv/), then retry."
        )

    if mode() == "tool":
        run_streaming(pip_install_command(name), progress_cb)
    else:
        # --inexact so installing this extra never uninstalls another one.
        run_streaming(sync_command([name], inexact=True), progress_cb)

    if not extra_installed(name):
        raise EngineInstallError(f"{EXTRAS[name][0]} installed but still can't be imported")
    _write_state(extras=sorted(installed_extras()))
    progress_cb(100.0, "installed")


def remove_extra(name: str) -> None:
    if name not in EXTRAS:
        raise EngineInstallError(f"Unknown engine package set: {name}")
    remaining = installed_extras() - {name}

    if any(mod in sys.modules for mod in _LOADED_ROOTS[name]):
        if _managed():
            _write_state(extras=sorted(remaining), resync_pending=True)
            raise RemovalNeedsRestart(
                f"{EXTRAS[name][0]} is in use; it will be removed the next time DocBox starts."
            )
        raise RemovalNeedsRestart(
            f"{EXTRAS[name][0]} is loaded in the running backend; restart it, then retry."
        )
    if not can_install():
        raise EngineInstallError("DocBox can't modify its packages here (no `uv` available).")

    if mode() == "tool":
        # No lock file to sync against: uninstall the packages only this extra needs.
        run_streaming(
            [_uv() or "uv", "pip", "uninstall", "--python", sys.executable,
             *sorted(_exclusive_dists(name))],
            lambda _p, _m: None, failure="Package removal failed",
        )
    else:
        # Exact sync with the remaining extras removes exactly this extra's packages.
        run_streaming(
            sync_command(remaining, inexact=False), lambda _p, _m: None,
            failure="Package removal failed",
        )
    _write_state(extras=sorted(installed_extras()), resync_pending=False)


def _dist_closure(roots: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        name = stack.pop().lower().replace("_", "-")
        if name in seen:
            continue
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        seen.add(name)
        for req_str in dist.requires or []:
            req = Requirement(req_str)
            if req.marker is not None and not req.marker.evaluate({"extra": ""}):
                continue
            stack.append(req.name)
    return seen


def _base_root_dists() -> list[str]:
    import tomllib

    try:
        data = tomllib.loads((project_dir() / "pyproject.toml").read_text(encoding="utf-8"))
        return [Requirement(r).name for r in data.get("project", {}).get("dependencies", [])]
    except OSError:
        pass
    # Tool mode: no pyproject.toml, but the installed distribution lists the same thing.
    try:
        declared = importlib.metadata.requires("docbox") or []
    except importlib.metadata.PackageNotFoundError:
        return []
    return [
        r.name for r in map(Requirement, declared)
        if r.marker is None or r.marker.evaluate({"extra": ""})
    ]


def _exclusive_dists(name: str) -> set[str]:
    """Distributions only this extra needs: not the base install's, not another
    installed extra's."""
    others = set().union(
        *(_dist_closure(_EXTRA_ROOT_DISTS[e]) for e in installed_extras() if e != name)
    )
    return _dist_closure(_EXTRA_ROOT_DISTS[name]) - _dist_closure(_base_root_dists()) - others


def _dist_bytes(name: str) -> int:
    try:
        dist = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return 0
    total = 0
    for f in dist.files or []:
        try:
            total += Path(dist.locate_file(f)).stat().st_size
        except OSError:
            pass
    return total


def extra_package_bytes(name: str) -> int:
    """Disk used by packages that only this extra needs (shared deps aren't counted)."""
    if not extra_installed(name):
        return 0
    return sum(_dist_bytes(d) for d in _exclusive_dists(name))
