"""OCREngine implementation that delegates to a locally-running Ollama server.

Ollama itself is a prerequisite (installed via `core/prerequisites.py`'s guided/one-click
install). Models, though, are pulled through Ollama's own API (`POST /api/pull`), so
picking an Ollama model in DocBox works like any other model: one click, real progress.
The weights live in Ollama's store, not DocBox's — `delete()` asks Ollama to remove them.

Nothing here leaves the machine except Ollama's own model download — its HTTP API is
bound to 127.0.0.1 by default, same trust boundary as DocBox's own backend.

The base URL is overridable via `DOCBOX_OLLAMA_BASE_URL` so this still works when the
backend itself is containerized (see the Dockerfile/docker-compose.yml): from inside a
container, 127.0.0.1 means the container, not the host running Ollama.
"""

from __future__ import annotations

import base64
import io
import json
import os
import threading
import time
from collections.abc import Iterable

import requests
from PIL import Image

from docbox.backend.engines.base import ProgressCallback
from docbox.backend.schemas import OcrLine, OcrResult

OLLAMA_BASE_URL = os.environ.get("DOCBOX_OLLAMA_BASE_URL", "http://127.0.0.1:11434")

_OCR_PROMPT = (
    "Transcribe all text visible in this image verbatim, preserving line breaks. "
    "Output only the transcribed text, with no commentary, preamble, or markdown "
    "formatting."
)


# A running local Ollama answers /api/tags in milliseconds. A *missing* one is the slow
# case: on Windows a refused loopback connection takes ~2 s to fail, and one model
# listing asks several times. So: a short timeout, and one shared answer per few seconds.
_TAGS_TIMEOUT_S = 1.0
_TAGS_TTL_S = 5.0
_tags_lock = threading.Lock()
_tags_cache: tuple[float, list[dict] | None] | None = None


def fetch_tags(*, fresh: bool = False) -> list[dict] | None:
    """Ollama's pulled models, or None if Ollama isn't reachable."""
    global _tags_cache
    with _tags_lock:
        cached = _tags_cache
    if not fresh and cached and time.monotonic() - cached[0] < _TAGS_TTL_S:
        return cached[1]
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=_TAGS_TIMEOUT_S)
        resp.raise_for_status()
        tags = resp.json().get("models", [])
    except requests.RequestException:
        tags = None
    with _tags_lock:
        _tags_cache = (time.monotonic(), tags)
    return tags


def clear_tags_cache() -> None:
    global _tags_cache
    with _tags_lock:
        _tags_cache = None


def normalize_model_name(name: str) -> str:
    # Ollama lists `llava` as `llava:latest`; treat the two spellings as the same model.
    return name if ":" in name else f"{name}:latest"


def pull_progress(lines: Iterable[bytes], progress_cb: ProgressCallback) -> float | None:
    """Consume Ollama's NDJSON pull stream, reporting progress; return the final % or
    None if the stream ended without "success". Raises on an error line.

    A pull downloads several layers, each reported with its own `digest`/`total`/
    `completed`; overall progress is the byte sum across every layer seen so far.
    """
    totals: dict[str, int] = {}
    done: dict[str, int] = {}
    pct = 0.0
    for raw in lines:
        if not raw:
            continue
        msg = json.loads(raw)
        if "error" in msg:
            raise RuntimeError(f"Ollama: {msg['error']}")
        status = msg.get("status", "")
        digest = msg.get("digest")
        if digest and msg.get("total"):
            totals[digest] = int(msg["total"])
            done[digest] = int(msg.get("completed", 0))
            pct = min(99.0, 100.0 * sum(done.values()) / max(1, sum(totals.values())))
        progress_cb(pct, status)
        if status == "success":
            return 100.0
    return None


def _image_to_b64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class OllamaOcrEngine:
    """Runs OCR-style transcription through a vision model already pulled in Ollama."""

    # The model runs inside Ollama's own server, not in this process (see base.py).
    runs_in_process = False

    def __init__(self, *, model_id: str, ollama_model: str) -> None:
        self._model_id = model_id
        self._ollama_model = ollama_model

    def is_downloaded(self, *, fresh: bool = False) -> bool:
        tags = fetch_tags(fresh=fresh)
        if tags is None:
            return False
        names = {normalize_model_name(n) for m in tags if (n := m.get("name"))}
        return normalize_model_name(self._ollama_model) in names

    def download(self, progress_cb: ProgressCallback) -> None:
        if self.is_downloaded(fresh=True):
            progress_cb(100.0, "already available via Ollama")
            return
        try:
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/pull",
                json={"model": self._ollama_model, "stream": True},
                stream=True,
                timeout=(5, 600),
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Couldn't reach Ollama to pull the model: {exc}") from None

        with resp:
            pct = pull_progress(resp.iter_lines(), progress_cb)
        if pct is None or not self.is_downloaded(fresh=True):
            raise RuntimeError(f"Ollama finished, but '{self._ollama_model}' isn't listed")
        progress_cb(100.0, "ready")

    def delete(self) -> None:
        try:
            resp = requests.delete(
                f"{OLLAMA_BASE_URL}/api/delete", json={"model": self._ollama_model}, timeout=30
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Ollama couldn't delete '{self._ollama_model}': {exc}") from None
        finally:
            clear_tags_cache()

    def load(self) -> None:
        pass

    def run(self, image: Image.Image) -> OcrResult:
        payload = {
            "model": self._ollama_model,
            "prompt": _OCR_PROMPT,
            "images": [_image_to_b64(image)],
            "stream": False,
        }
        try:
            resp = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=120)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from None

        text = resp.json().get("response", "").strip()
        lines = [OcrLine(text=line, confidence=None) for line in text.splitlines() if line.strip()]
        return OcrResult(model_id=self._model_id, lines=lines, text=text)
