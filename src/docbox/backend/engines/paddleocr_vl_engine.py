"""OCREngine implementation for PaddleOCR-VL — a layout-detection + vision-language-model
document parsing pipeline (`paddleocr.PaddleOCRVL`), verified against paddleocr==3.7.0.

This is a genuinely heavier "nature" of model than the classic PP-OCR det+rec pipelines:
a ~0.9B-parameter VLM does the recognition step, registered in paddlex's official model
catalog as `"PaddleOCR-VL"`. It is registered in `models_catalog.py` with correspondingly
large RAM/disk estimates so the hardware-fit check steers most machines away from it —
that's the intended UX for a heavy model, not a bug.

Notes verified via source inspection (not a full download+run, given the model's size):

- Cache/env handling is identical to `paddleocr_engine.py`: `PADDLE_PDX_CACHE_HOME` env
  var, `<cache_root>/official_models/<model_name>/` existence check.
- `PaddleOCRVL().predict(path)` returns a generator of result objects exposing a
  `.markdown` property (`{"markdown_texts": str, ...}`, from paddlex's `MarkdownMixin`)
  rather than the simple `rec_texts`/`rec_scores` lists the classic pipelines expose —
  this pipeline parses whole-document layout (headings, paragraphs, tables) into
  markdown, not a flat list of text lines, so line-level confidence isn't available here
  and `OcrLine.confidence` is left `None`.
- Devices work as in `paddleocr_engine.py`: `device="gpu:0"` on the graphics card, and back
  to the processor when the card fails to load it or on the first page, or runs out of
  memory.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from docbox.backend.core.paths import get_models_dir
from docbox.backend.engines.base import ProgressCallback
from docbox.backend.engines.cuda import add_nvidia_dll_dirs
from docbox.backend.engines.paddleocr_engine import check_paddle_cuda, paddle_device
from docbox.backend.schemas import OcrLine, OcrResult

_MODEL_NAME = "PaddleOCR-VL"


def _cache_root() -> Path:
    d = get_models_dir() / "paddlex_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _set_cache_env() -> None:
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(_cache_root()))
    add_nvidia_dll_dirs()


def _model_dir() -> Path:
    return _cache_root() / "official_models" / _MODEL_NAME


class PaddleOcrVlEngine:
    """PaddleOCR-VL layout+VLM document parsing pipeline, on the processor or (with
    `use_device("gpu")`) the graphics card."""

    def __init__(self, *, model_id: str, device: str = "cpu") -> None:
        self._model_id = model_id
        self._device = device
        self._pipeline = None
        self._pages_read = 0

    def use_device(self, device: str) -> None:
        if device != self._device:
            self._device = device
            self._pipeline = None

    @property
    def device(self) -> str:
        return self._device

    def is_downloaded(self) -> bool:
        return _model_dir().exists()

    def download(self, progress_cb: ProgressCallback) -> None:
        _set_cache_env()

        if self.is_downloaded():
            progress_cb(100.0, "already downloaded")
            return

        try:
            from paddlex.inference.utils.official_models import official_models

            progress_cb(5.0, f"downloading {_MODEL_NAME} (large VLM, this can take a while)")
            official_models[_MODEL_NAME]
            progress_cb(95.0, "finalizing")
        except ImportError:
            progress_cb(5.0, "downloading model")
            self._build_pipeline()

        if not self.is_downloaded():
            raise RuntimeError("Model download reported success but files are missing on disk")

        progress_cb(100.0, "ready")

    def _build_pipeline(self):
        _set_cache_env()
        from paddleocr import PaddleOCRVL

        if self._device == "gpu":
            check_paddle_cuda()
        return PaddleOCRVL(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            device=paddle_device(self._device),
        )

    def load(self) -> None:
        if self._pipeline is not None:
            return
        if not self.is_downloaded():
            raise RuntimeError("Model is not downloaded yet")
        self._pipeline = self._build_pipeline()

    def run(self, image: Image.Image) -> OcrResult:
        if self._pipeline is None:
            self.load()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "input.png"
            image.save(tmp_path)
            try:
                results = list(self._pipeline.predict(str(tmp_path)))
            except Exception as exc:
                from docbox.backend.core import gpu

                if self._device != "gpu" or (
                    self._pages_read and not gpu.is_out_of_memory(exc)
                ):
                    raise
                gpu.record_fallback(self._model_id, gpu.fallback_message(exc))
                self.use_device("cpu")
                self.load()
                results = list(self._pipeline.predict(str(tmp_path)))
        self._pages_read += 1

        lines: list[OcrLine] = []
        for res in results:
            markdown_text = res.markdown.get("markdown_texts", "") if hasattr(res, "markdown") else ""
            for raw_line in markdown_text.splitlines():
                stripped = raw_line.strip()
                if stripped:
                    lines.append(OcrLine(text=stripped, confidence=None))

        return OcrResult(
            model_id=self._model_id,
            lines=lines,
            text="\n".join(line.text for line in lines),
        )

    def delete(self) -> None:
        self._pipeline = None
        shutil.rmtree(_model_dir(), ignore_errors=True)
