"""External programs some engines need (Ollama, Tesseract): detect, guide, install.

These are real OS-level programs, so DocBox never installs them *silently*. On Windows
the user can click Install, which runs winget; winget/Windows then show their own UAC
prompt, so the user confirms twice. On Linux they need sudo, which a GUI app shouldn't
prompt for, so DocBox shows the exact command for the user's distro instead. Either way,
"Check again" re-detects afterwards.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from docbox.backend.core.paths import MACOS_BIN_DIRS
from docbox.backend.core.runtime import run_streaming
from docbox.backend.engines.base import ProgressCallback
from docbox.backend.engines.tesseract_engine import find_tesseract_binary
from docbox.backend.platforms import ollama as ollama_platform

PREREQUISITES: dict[str, dict[str, str]] = {
    "ollama": {
        "name": "Ollama",
        "winget_id": "Ollama.Ollama",
        "download_url": "https://ollama.com/download",
        "about": "Runs vision-language models locally. DocBox pulls models through it.",
    },
    "tesseract": {
        "name": "Tesseract OCR",
        "winget_id": "UB-Mannheim.TesseractOCR",
        "download_url": "https://github.com/UB-Mannheim/tesseract/wiki",
        "about": "The classic Tesseract OCR program. DocBox downloads its language data.",
    },
}


_OLLAMA_MAC_APP = Path("/Applications/Ollama.app")


def _ollama_binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        candidates = [Path(local) / "Programs" / "Ollama" / "ollama.exe"] if local else []
    elif sys.platform == "darwin":
        candidates = [
            *(d / "ollama" for d in MACOS_BIN_DIRS),
            _OLLAMA_MAC_APP / "Contents" / "Resources" / "ollama",
        ]
    else:
        return None
    return next((str(c) for c in candidates if c.exists()), None)


def state(prereq_id: str, *, fresh: bool = False) -> str:
    """"ready", "installed" (Ollama installed but not running) or "missing".

    `fresh` skips the short-lived Ollama status cache; use it wherever the user just
    acted (Check again, after an install) rather than in bulk model listings.
    """
    if prereq_id == "tesseract":
        return "ready" if find_tesseract_binary() else "missing"
    if prereq_id == "ollama":
        if ollama_platform.is_running(fresh=fresh):
            return "ready"
        return "installed" if _ollama_binary() else "missing"
    raise KeyError(prereq_id)


def is_satisfied(prereq_id: str) -> bool:
    return state(prereq_id) == "ready"


def can_auto_install() -> bool:
    return sys.platform == "win32" and shutil.which("winget") is not None


def _os_release() -> dict[str, str]:
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return {}
    pairs = (line.split("=", 1) for line in text.splitlines() if "=" in line)
    return {k: v.strip().strip('"') for k, v in pairs}


def manual_commands(prereq_id: str) -> list[str]:
    if sys.platform == "win32":
        winget_id = PREREQUISITES[prereq_id]["winget_id"]
        return [f"winget install -e --id {winget_id}"]
    if prereq_id == "ollama":
        if sys.platform == "darwin":
            return ["brew install ollama"]
        return ["curl -fsSL https://ollama.com/install.sh | sh"]
    if sys.platform == "darwin":
        return ["brew install tesseract"]
    rel = _os_release()
    family = f"{rel.get('ID', '')} {rel.get('ID_LIKE', '')}".lower()
    if "debian" in family or "ubuntu" in family:
        return ["sudo apt install -y tesseract-ocr"]
    if any(d in family for d in ("fedora", "rhel", "centos")):
        return ["sudo dnf install -y tesseract"]
    if "arch" in family:
        return ["sudo pacman -S --needed tesseract"]
    if "suse" in family:
        return ["sudo zypper install -y tesseract-ocr"]
    return [
        "sudo apt install -y tesseract-ocr   # Debian/Ubuntu",
        "sudo dnf install -y tesseract       # Fedora",
        "sudo pacman -S --needed tesseract   # Arch",
    ]


def describe(prereq_id: str) -> dict:
    meta = PREREQUISITES[prereq_id]
    current = state(prereq_id, fresh=True)
    return {
        "id": prereq_id,
        "name": meta["name"],
        "about": meta["about"],
        "state": current,
        "can_auto_install": current == "missing" and can_auto_install(),
        "can_start": current == "installed",
        "commands": manual_commands(prereq_id),
        "download_url": meta["download_url"],
    }


def list_all() -> list[dict]:
    return [describe(p) for p in PREREQUISITES]


def start_ollama() -> None:
    binary = _ollama_binary()
    if binary is None:
        raise RuntimeError("Ollama isn't installed")
    if sys.platform == "win32":
        # Prefer the tray app (what Ollama's own installer launches); it runs the server.
        tray = Path(binary).with_name("ollama app.exe")
        cmd = [str(tray)] if tray.exists() else [binary, "serve"]
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(cmd, creationflags=flags, close_fds=True)
    elif sys.platform == "darwin" and _OLLAMA_MAC_APP.exists():
        # The menu-bar app, as Ollama's own installer sets it up; it runs the server.
        subprocess.Popen(["open", "-a", str(_OLLAMA_MAC_APP)])
    else:
        subprocess.Popen(
            [binary, "serve"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _friendly_winget_progress(name: str, progress_cb: ProgressCallback) -> ProgressCallback:
    """winget prints URLs, hashes and block-character bars; show people plain steps."""

    def cb(pct: float, line: str) -> None:
        low = line.lower()
        if low.startswith("downloading"):
            message = f"Downloading {name}"
        elif "hash" in low:
            message = "Checking the download"
        elif "install" in low and "success" not in low:
            message = f"Installing {name}. Approve the Windows prompt if one appears."
        elif "success" in low:
            message = f"{name} installed"
        else:
            message = f"Setting up {name}"
        progress_cb(pct, message)

    return cb


def install(prereq_id: str, progress_cb: ProgressCallback) -> None:
    if not can_auto_install():
        raise RuntimeError("One-click install needs Windows with winget; use the shown command.")
    winget_id = PREREQUISITES[prereq_id]["winget_id"]
    name = PREREQUISITES[prereq_id]["name"]
    cmd = [
        "winget", "install", "-e", "--id", winget_id, "--silent",
        "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity",
    ]
    try:
        run_streaming(
            cmd,
            _friendly_winget_progress(name, progress_cb),
            failure=f"winget couldn't install {winget_id}",
        )
    except RuntimeError:
        # winget exits non-zero for some benign cases (already installed); trust detection.
        if state(prereq_id, fresh=True) == "missing":
            raise
    if prereq_id == "ollama" and state("ollama", fresh=True) == "installed":
        start_ollama()
    if state(prereq_id, fresh=True) == "missing":
        raise RuntimeError(
            f"{PREREQUISITES[prereq_id]['name']} still isn't detected after installing. "
            "Restarting DocBox may help."
        )
    progress_cb(100.0, "installed")
