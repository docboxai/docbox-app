"""OCREngine implementation backed by Tesseract OCR (via `pytesseract`).

A genuinely different "nature" of engine from the PaddleOCR family: a classical
(non-deep-learning-pipeline, though its LSTM mode does use a neural net internally)
engine that ships as a standalone system binary rather than a pip-installable model.

Two-tier "download" story, deliberately kept honest rather than papered over:

1. The `tesseract` binary itself is a real OS-level install (an installer on Windows, a
   system package on Linux) that this app will NOT silently fetch and execute — doing so
   without explicit user action would mean running an untrusted installer/binary with no
   confirmation, which is not something to automate. `is_downloaded()` / `download()`
   detect its absence and surface clear, actionable manual-install instructions instead
   of pretending to handle it.
2. Once the binary is present, the per-language `.traineddata` file *is* something this
   app can safely fetch itself (a plain data file, not an executable) — that part goes
   through the normal download-with-progress flow, sourced from the official
   `tesseract-ocr/tessdata_fast` GitHub repo (the same lightweight variant the Tesseract
   project recommends for typical use over the much larger `tessdata_best`).
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import requests
from PIL import Image

from docbox.backend.core.paths import get_models_dir
from docbox.backend.engines.base import ProgressCallback
from docbox.backend.schemas import OcrLine, OcrResult

_TESSDATA_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/{lang}.traineddata"
)

_INSTALL_INSTRUCTIONS = {
    "win32": (
        "Tesseract OCR binary not found. Install it from "
        "https://github.com/UB-Mannheim/tesseract/wiki (Windows installer), "
        "then click Download again."
    ),
    "linux": (
        "Tesseract OCR binary not found. Install it with your package manager, e.g. "
        "`sudo apt install tesseract-ocr` (Debian/Ubuntu) or `sudo dnf install tesseract` "
        "(Fedora), then click Download again."
    ),
}


def _tessdata_dir() -> Path:
    d = get_models_dir() / "tesseract" / "tessdata"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _traineddata_path(lang: str) -> Path:
    return _tessdata_dir() / f"{lang}.traineddata"


def _windows_default_binaries() -> list[Path]:
    # The UB-Mannheim installer (what winget installs) doesn't add itself to PATH.
    roots = [os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")]
    candidates = [Path(r) / "Tesseract-OCR" / "tesseract.exe" for r in roots if r]
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(
            Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Tesseract-OCR" / "tesseract.exe"
        )
    return candidates


def find_tesseract_binary() -> str | None:
    found = shutil.which("tesseract")
    if found or sys.platform != "win32":
        return found
    for candidate in _windows_default_binaries():
        if candidate.exists():
            return str(candidate)
    return None


class TesseractEngine:
    """Tesseract OCR for a specific language. CPU-only (Tesseract has no GPU mode)."""

    def __init__(self, *, model_id: str, lang: str) -> None:
        self._model_id = model_id
        self._lang = lang

    def is_downloaded(self) -> bool:
        return find_tesseract_binary() is not None and _traineddata_path(self._lang).exists()

    def download(self, progress_cb: ProgressCallback) -> None:
        binary = find_tesseract_binary()
        if binary is None:
            raise RuntimeError(
                _INSTALL_INSTRUCTIONS.get(sys.platform, _INSTALL_INSTRUCTIONS["linux"])
            )

        if _traineddata_path(self._lang).exists():
            progress_cb(100.0, "already downloaded")
            return

        url = _TESSDATA_URL_TEMPLATE.format(lang=self._lang)
        progress_cb(2.0, f"downloading {self._lang}.traineddata")

        dest = _traineddata_path(self._lang)
        with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)
            with requests.get(url, stream=True, timeout=30) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    tmp_file.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        progress_cb(min(99.0, 100.0 * downloaded / total), "downloading")

        tmp_path.replace(dest)
        progress_cb(100.0, "ready")

    def load(self) -> None:
        binary = find_tesseract_binary()
        if binary is None:
            raise RuntimeError(
                _INSTALL_INSTRUCTIONS.get(sys.platform, _INSTALL_INSTRUCTIONS["linux"])
            )
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = binary

    def run(self, image: Image.Image) -> OcrResult:
        self.load()
        import pytesseract
        from pytesseract import Output

        data = pytesseract.image_to_data(
            image,
            lang=self._lang,
            config=f'--tessdata-dir "{_tessdata_dir()}"',
            output_type=Output.DICT,
        )

        # Group recognized words into lines by (block, paragraph, line) triple, matching
        # Tesseract's own TSV line grouping.
        line_words: dict[tuple[int, int, int], list[tuple[str, float]]] = {}
        for i, text in enumerate(data["text"]):
            word = text.strip()
            if not word:
                continue
            conf = float(data["conf"][i])
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            line_words.setdefault(key, []).append((word, conf))

        lines: list[OcrLine] = []
        for words in line_words.values():
            text = " ".join(w for w, _ in words)
            confidences = [c for _, c in words if c >= 0]
            avg_conf = (sum(confidences) / len(confidences) / 100.0) if confidences else None
            lines.append(OcrLine(text=text, confidence=avg_conf))

        return OcrResult(
            model_id=self._model_id,
            lines=lines,
            text="\n".join(line.text for line in lines),
        )

    def delete(self) -> None:
        _traineddata_path(self._lang).unlink(missing_ok=True)
