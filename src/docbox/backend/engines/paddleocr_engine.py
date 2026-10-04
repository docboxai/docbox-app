"""OCREngine implementation backed by the `paddleocr` package (PaddlePaddle PP-OCR).

Verified against paddleocr==3.7.0 / paddlex (installed via `uv sync`):

- Model cache root is controlled by the `PADDLE_PDX_CACHE_HOME` env var (paddlex falls
  back to `~/.paddlex` otherwise) — must be set *before* `paddleocr`/`paddlex` is
  imported, since paddlex reads it once at import time into a module-level constant.
- Downloaded models land at `<cache_root>/official_models/<model_name>/`; existence of
  that directory is exactly the check paddlex itself uses to decide "already cached".
- `PaddleOCR(text_detection_model_name=..., text_recognition_model_name=...,
  use_doc_orientation_classify=False, use_doc_unwarping=False,
  use_textline_orientation=False)` runs a specific det+rec pair directly (bypassing
  `lang`/`ocr_version` auto-resolution), skipping the heavier optional
  doc-orientation/unwarping/textline-orientation sub-models. Real det/rec model id pairs
  for different size/language tiers are verified against paddlex's official model
  catalog (`paddlex/inference/utils/official_models.py::ALL_MODELS`) in
  `models_catalog.py`, not guessed here.
- `.predict(image)` returns a generator of dict-like result objects with `res["rec_texts"]`
  (list[str]) and `res["rec_scores"]` (list[float]).
- The bundled downloader has no byte-level progress callback (only an internal
  `print_progress` console flag) — this engine reports coarse, stage-based progress
  instead of a byte-accurate percentage.
- paddlepaddle 3.x's default oneDNN/PIR fusion path raises `NotImplementedError:
  ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<...>]` for some
  det models on CPU (reproduced on this machine for PP-OCRv4_mobile_det); disabling
  MKL-DNN (`enable_mkldnn=False`) avoids that broken path at a small inference-speed cost.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from docbox.backend.core.paths import get_models_dir
from docbox.backend.engines.base import ProgressCallback
from docbox.backend.schemas import OcrLine, OcrResult


def _cache_root() -> Path:
    # A dedicated subdirectory under our own models dir, kept separate from
    # DocBox's other per-model bookkeeping.
    d = get_models_dir() / "paddlex_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _set_cache_env() -> None:
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(_cache_root()))


def _model_dir(model_name: str) -> Path:
    return _cache_root() / "official_models" / model_name


class PaddleOcrEngine:
    """A PaddleOCR (PP-OCR) detection + recognition pipeline for a specific det/rec
    model pair. CPU-only for v1; `device` is a forward-compat slot for a future
    `"cuda"` value."""

    def __init__(
        self,
        *,
        model_id: str,
        det_model_name: str,
        rec_model_name: str,
        device: str = "cpu",
    ) -> None:
        self._model_id = model_id
        self._det_model_name = det_model_name
        self._rec_model_name = rec_model_name
        self._device = device
        self._ocr = None

    def is_downloaded(self) -> bool:
        return (
            _model_dir(self._det_model_name).exists()
            and _model_dir(self._rec_model_name).exists()
        )

    def download(self, progress_cb: ProgressCallback) -> None:
        _set_cache_env()

        if self.is_downloaded():
            progress_cb(100.0, "already downloaded")
            return

        try:
            # Internal paddlex API: `official_models[name]` resolves the local path,
            # downloading on first access. Calling it per-model gives us real two-stage
            # progress; if this internal path ever moves, fall back to a single-stage
            # download further below.
            from paddlex.inference.utils.official_models import official_models

            progress_cb(5.0, f"downloading {self._det_model_name}")
            official_models[self._det_model_name]
            progress_cb(55.0, f"downloading {self._rec_model_name}")
            official_models[self._rec_model_name]
            progress_cb(95.0, "finalizing")
        except ImportError:
            progress_cb(5.0, "downloading models")
            self._build_pipeline()

        if not self.is_downloaded():
            raise RuntimeError("Model download reported success but files are missing on disk")

        progress_cb(100.0, "ready")

    def _build_pipeline(self):
        _set_cache_env()
        from paddleocr import PaddleOCR

        return PaddleOCR(
            text_detection_model_name=self._det_model_name,
            text_recognition_model_name=self._rec_model_name,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )

    def load(self) -> None:
        if self._ocr is not None:
            return
        if not self.is_downloaded():
            raise RuntimeError("Model is not downloaded yet")
        self._ocr = self._build_pipeline()

    def run(self, image: Image.Image) -> OcrResult:
        if self._ocr is None:
            self.load()

        # PaddleOCR's predict() accepts a path/ndarray; a temp file sidesteps having to
        # track its exact accepted in-memory array layout across versions.
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "input.png"
            image.save(tmp_path)
            results = list(self._ocr.predict(str(tmp_path)))

        lines: list[OcrLine] = []
        for res in results:
            texts = res.get("rec_texts", [])
            scores = res.get("rec_scores", [])
            # [x1, y1, x2, y2] per recognized line, when this paddleocr version reports it.
            boxes = res.get("rec_boxes")
            boxes = [] if boxes is None else list(boxes)
            for i, text in enumerate(texts):
                confidence = float(scores[i]) if i < len(scores) else None
                box = [float(v) for v in boxes[i][:4]] if i < len(boxes) else None
                lines.append(OcrLine(text=text, confidence=confidence, box=box))

        return OcrResult(
            model_id=self._model_id,
            lines=lines,
            text="\n".join(line.text for line in lines),
        )

    def model_names(self) -> tuple[str, str]:
        return self._det_model_name, self._rec_model_name

    def delete(self) -> None:
        # Several catalog entries share a model (e.g. every PP-OCRv5 language family uses
        # PP-OCRv5_server_det), so keep any dir another *downloaded* entry still needs.
        from docbox.backend.core.registry import registry

        in_use: set[str] = set()
        for spec in registry.list():
            if spec.id == self._model_id:
                continue
            other = spec.engine_factory()
            if isinstance(other, PaddleOcrEngine) and other.is_downloaded():
                in_use.update(other.model_names())

        self._ocr = None
        for name in self.model_names():
            if name not in in_use:
                shutil.rmtree(_model_dir(name), ignore_errors=True)
