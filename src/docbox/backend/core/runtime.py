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

PaddleOCR and EasyOCR also have a graphics-card build (`GPU_BUILDS`: the `paddle-gpu` and
`easyocr-gpu` extras, CUDA 12.6), installed in place of the CPU one only when the user
asks (`switch_build`). Each pair installs the same modules, so they're uv conflicts and a
switch is an exact sync; `installed_extras()` keeps naming the engine ("paddle") whichever
build it has, `build_of()` says which, and `synced_extras()` (what state.json records)
names the build ("paddle-gpu").
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
import threading
from collections.abc import Iterable
from pathlib import Path

from packaging.requirements import Requirement

from docbox.backend.core import atomic
from docbox.backend.core.paths import get_runtime_dir
from docbox.backend.engines.base import ProgressCallback

# extra name -> (human label, a top-level module that exists iff the extra is installed)
EXTRAS: dict[str, tuple[str, str]] = {
    "paddle": ("PaddleOCR engine", "paddleocr"),
    "easyocr": ("EasyOCR engine (PyTorch)", "easyocr"),
}

# Engine -> its graphics-card build. Windows and Linux on x86_64 only (gpu_builds_supported);
# only one of them at a time (pyproject.toml's conflicts).
GPU_BUILDS: dict[str, str] = {"paddle": "paddle-gpu", "easyocr": "easyocr-gpu"}
# What the graphics-card build downloads beyond the CPU one, in MB: the wheels uv.lock adds
# for it (Paddle's Linux build pulls NVIDIA's CUDA libraries, ~3.4 GB of it; on Windows it
# gets the same libraries as pyproject.toml lists them; torch's CUDA wheel is ~2.4 GB).
GPU_DOWNLOAD_MB: dict[tuple[str, str], int] = {
    ("paddle", "linux"): 3700,
    ("paddle", "win32"): 2200,
    ("easyocr", "linux"): 2900,
    ("easyocr", "win32"): 2500,
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
_GPU_ROOT_DISTS: dict[str, tuple[str, ...]] = {
    "paddle": (
        "paddleocr", "paddlepaddle-gpu",
        # Listed directly on Windows; on Linux paddlepaddle-gpu depends on them.
        "nvidia-cuda-runtime-cu12", "nvidia-cuda-nvrtc-cu12", "nvidia-cublas-cu12",
        "nvidia-cudnn-cu12", "nvidia-cufft-cu12", "nvidia-curand-cu12",
        "nvidia-cusolver-cu12", "nvidia-cusparse-cu12", "nvidia-nvjitlink-cu12",
    ),
    "easyocr": ("easyocr", "torch", "torchvision"),
}
# Distributions a switch between builds replaces (tool mode uninstalls them first: the
# two Paddle builds are differently named distributions of the same `paddle` module).
_SWAPPED_DISTS: dict[str, tuple[str, ...]] = {
    "paddle": ("paddlepaddle", "paddlepaddle-gpu"),
    "easyocr": ("torch", "torchvision"),
}

# What the `agents` extra installs (the MCP server). Not an engine DocBox installs or
# removes, but removing an engine must not take away packages the two share.
_NON_ENGINE_ROOT_DISTS: tuple[str, ...] = ("mcp",)


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
# The package indexes in pyproject.toml's [[tool.uv.index]]: PyTorch's CPU-only wheels (the
# `+cpu` pins), and the CUDA 12.6 wheels of PyTorch and Paddle for the graphics-card builds.
_TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
_GPU_INDEXES = (
    "https://download.pytorch.org/whl/cu126",
    "https://www.paddlepaddle.org.cn/packages/stable/cu126/",
)


def gpu_builds_supported() -> bool:
    """Whether the engines' graphics-card builds exist for this system."""
    import platform

    return sys.platform in ("win32", "linux") and platform.machine().lower() in (
        "x86_64", "amd64",
    )


def gpu_download_mb(name: str) -> int:
    return GPU_DOWNLOAD_MB.get((name, "win32" if sys.platform == "win32" else "linux"), 0)


def _pins_for(extra: str) -> Path:
    """Tool mode's pins for one extra: a graphics-card build's are exported apart, since
    uv.lock pins torch to +cpu for one and +cu126 for the other."""
    if extra in GPU_BUILDS.values():
        return _PINS / f"constraints-{extra}.txt"
    return _PINS / "constraints.txt"


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


# importlib.invalidate_caches() isn't thread-safe: two threads in it at once can both
# delete the same sys.path_importer_cache entry, and one fails with KeyError. Requests run
# on a thread pool, so the model list and the storage figures can call it together.
_FIND_LOCK = threading.Lock()


def installed_extras() -> set[str]:
    with _FIND_LOCK:
        importlib.invalidate_caches()
        return {
            name for name, (_label, marker) in EXTRAS.items()
            if importlib.util.find_spec(marker) is not None
        }


def extra_installed(name: str) -> bool:
    return name in installed_extras()


def _dist_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def build_of(name: str) -> str | None:
    """"gpu" or "cpu": which build of an engine is installed; None when it isn't."""
    if not extra_installed(name):
        return None
    if name == "paddle":
        return "gpu" if _dist_version("paddlepaddle-gpu") else "cpu"
    if name == "easyocr":
        return "gpu" if "+cu" in (_dist_version("torch") or "") else "cpu"
    return "cpu"


def synced_extras() -> set[str]:
    """The pyproject extras installed: each engine's, by the build it has."""
    return {
        GPU_BUILDS[name] if build_of(name) == "gpu" else name for name in installed_extras()
    }


def _family(extra: str) -> str:
    """The engine a build belongs to ("paddle-gpu" -> "paddle")."""
    return next((name for name, gpu in GPU_BUILDS.items() if gpu == extra), extra)


def state_engines() -> set[str]:
    """The engines state.json says the managed env should have (by engine, not build)."""
    return {_family(e) for e in read_state().get("extras", [])}


def _state_path() -> Path:
    return get_runtime_dir() / "state.json"


def read_state() -> dict:
    if not _managed():  # see _write_state
        return {}
    try:
        return json.loads(atomic.read_text(_state_path()))
    except (OSError, ValueError):
        return {}


def _write_state(**updates) -> None:
    # state.json describes the installed app's managed env, which the Tauri shell re-syncs
    # from it. A CLI, MCP server or dev backend shares the data dir but runs its own Python,
    # so its extras must never be written there.
    if not _managed():
        return
    state = read_state()
    state.update(updates)
    path = _state_path()
    atomic.write_text(path, json.dumps(state, indent=2))


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
    indexes = _GPU_INDEXES if name in GPU_BUILDS.values() else (_TORCH_CPU_INDEX,)
    return [
        _uv() or "uv", "pip", "install", "--python", sys.executable,
        "--constraints", str(_pins_for(name)),
        "--overrides", str(_PINS / "overrides.txt"),
        *(arg for url in indexes for arg in ("--extra-index-url", url)),
        "--index-strategy", "unsafe-best-match",
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
    _write_state(extras=sorted(synced_extras()))
    progress_cb(100.0, "installed")


class GpuBuildTaken(EngineInstallError):
    """Another engine's graphics-card build is installed; only one can be."""


def switch_build(name: str, build: str, progress_cb: ProgressCallback) -> None:
    """Install an engine's graphics-card build ("gpu") or CPU build ("cpu") in place of the
    other (or of nothing, when the engine isn't installed yet)."""
    if name not in GPU_BUILDS or build not in ("cpu", "gpu"):
        raise EngineInstallError(f"No {build} build of {name}")
    if build == "gpu" and not gpu_builds_supported():
        raise EngineInstallError(
            "The graphics-card builds are for Windows and Linux on x86_64 only."
        )
    current = build_of(name)
    if current == build:
        progress_cb(100.0, "already installed")
        return
    target = GPU_BUILDS[name] if build == "gpu" else name
    others = synced_extras() - {name, GPU_BUILDS[name]}
    taken = [e for e in others if build == "gpu" and e in GPU_BUILDS.values()]
    if taken:
        raise GpuBuildTaken(
            f"{EXTRAS[_family(taken[0])][0]} already uses the graphics card, and only one "
            "engine can: switch it back to the processor first."
        )
    label = EXTRAS[name][0]
    where = "the graphics card" if build == "gpu" else "the processor"
    if current is not None and any(mod in sys.modules for mod in _LOADED_ROOTS[name]):
        if _managed():
            _write_state(extras=sorted(others | {target}), resync_pending=True)
            raise RemovalNeedsRestart(
                f"{label} is in use; it switches to {where} the next time DocBox starts."
            )
        raise RemovalNeedsRestart(
            f"{label} is loaded in the running backend; restart it, then retry."
        )
    if not can_install():
        raise EngineInstallError("DocBox can't modify its packages here (no `uv` available).")

    if mode() == "tool":
        if current is not None:
            run_streaming(
                [_uv() or "uv", "pip", "uninstall", "--python", sys.executable,
                 *_SWAPPED_DISTS[name]],
                lambda _p, _m: None, failure="Package removal failed",
            )
        run_streaming(pip_install_command(target), progress_cb)
    else:
        # Exact, so the other build's packages go; every other engine is listed, so its
        # packages stay.
        run_streaming(sync_command(others | {target}, inexact=False), progress_cb)

    if build_of(name) != build:
        raise EngineInstallError(f"{label} for {where} installed but still can't be imported")
    _write_state(extras=sorted(synced_extras()), resync_pending=False)
    progress_cb(100.0, "installed")


def remove_extra(name: str) -> None:
    if name not in EXTRAS:
        raise EngineInstallError(f"Unknown engine package set: {name}")
    remaining = synced_extras() - {name, GPU_BUILDS.get(name, name)}

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
    _write_state(extras=sorted(synced_extras()), resync_pending=False)


def _root_dists(name: str) -> tuple[str, ...]:
    """The distributions an engine's installed build pulls in directly."""
    if build_of(name) == "gpu":
        return _GPU_ROOT_DISTS[name]
    return _EXTRA_ROOT_DISTS[name]


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
    installed extra's (engines, or the MCP server's when it's installed)."""
    others = set().union(
        *(_dist_closure(_root_dists(e)) for e in installed_extras() if e != name),
        _dist_closure(_NON_ENGINE_ROOT_DISTS),
    )
    return _dist_closure(_root_dists(name)) - _dist_closure(_base_root_dists()) - others


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
