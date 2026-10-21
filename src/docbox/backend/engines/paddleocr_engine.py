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
- oneDNN (`enable_mkldnn`) must stay on. Without it paddle's CPU convolutions hold about
  5 GB per megapixel of detector input (PP-OCRv5_server_det: 1000x1000 peaked at 5.5 GB,
  a 1920x13768 screenshot was OOM-killed at 8.5 GB, issue #23); with it the same image
  peaks under 2 GB and reads ~10x faster. paddlepaddle 3.3 breaks oneDNN for every det
  model (`ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<...>]`),
  hence `paddlepaddle<3.3` in pyproject.toml.
- Paddle shrinks an image whose long side is over 4000 px before looking for text, so the
  text of a tall screenshot gets too small to find (a 1920x13768 one read 232 lines whole,
  449 in strips). `_strips()` cuts such images, and very large ones, into overlapping
  full-resolution strips, which also caps the detector's memory at about a page's worth.
- On a graphics card (`use_device("gpu")`, with the `paddle-gpu` build installed; core/gpu.py
  decides) the pipeline gets `device="gpu:0"`. If the card fails while loading or on the
  first page, or runs out of memory on any page, the engine rebuilds itself on the
  processor and reads that page again (`_fall_back`).
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
from docbox.backend.schemas import OcrLine, OcrResult


def _cache_root() -> Path:
    # A dedicated subdirectory under our own models dir, kept separate from
    # DocBox's other per-model bookkeeping.
    d = get_models_dir() / "paddlex_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _set_cache_env() -> None:
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(_cache_root()))
    add_nvidia_dll_dirs()


def check_paddle_cuda() -> None:
    """Raise unless Paddle is the CUDA build and sees a graphics card."""
    import paddle

    if not paddle.device.is_compiled_with_cuda():
        raise RuntimeError("the installed Paddle is its CPU build")
    if paddle.device.cuda.device_count() < 1:
        raise RuntimeError("Paddle found no CUDA graphics card")


def paddle_device(device: str) -> str:
    return "gpu:0" if device == "gpu" else "cpu"


def _model_dir(model_name: str) -> Path:
    return _cache_root() / "official_models" / model_name


# Paddle's own limit: it shrinks images whose long side is over this before detection.
_MAX_SIDE = 4000
# The most pixels the detector gets at once: just over an A4 page at 200 dpi (1654x2339),
# so ordinary pages are read whole and memory stays at a page's worth. The catalog's
# measured `approx_ram_mb` figures are for this much (a 1920x2000 page); raise it and they
# no longer hold.
_STRIP_PIXELS = 3_900_000
# Strips overlap by more than a tall line of text, so every line lies whole in one of them.
_OVERLAP = 200


def _strips(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """(left, top, right, bottom) of the strips to read: the whole image when it's small
    enough, else overlapping strips across its long side."""
    long_side = max(width, height)
    if long_side <= _MAX_SIDE and width * height <= _STRIP_PIXELS:
        return [(0, 0, width, height)]
    short_side = min(width, height)
    step_len = max(min(_MAX_SIDE, _STRIP_PIXELS // short_side), 4 * _OVERLAP)
    starts = list(range(0, long_side - _OVERLAP, step_len - _OVERLAP)) or [0]
    spans = [(start, min(start + step_len, long_side)) for start in starts]
    if height >= width:
        return [(0, top, width, bottom) for top, bottom in spans]
    return [(left, 0, right, height) for left, right in spans]


def _owned(strip: tuple[int, int, int, int], strips: list, box: list[float]) -> bool:
    """Whether a line found in `strip` belongs to it rather than to the strip overlapping
    it: its centre lies in this strip's half of each overlap."""
    vertical = strips[-1][1] > 0
    lo, hi = (strip[1], strip[3]) if vertical else (strip[0], strip[2])
    centre = (box[1] + box[3]) / 2 if vertical else (box[0] + box[2]) / 2
    first, last = strip is strips[0], strip is strips[-1]
    return (first or centre >= lo + _OVERLAP / 2) and (last or centre < hi - _OVERLAP / 2)


def _same_line(a: OcrLine, b: OcrLine) -> bool:
    """Whether two strips read the same line: a line centred on the cut between them can
    come back a pixel apart from each, so both would own it."""
    if a.text != b.text or a.box is None or b.box is None:
        return False
    w = min(a.box[2], b.box[2]) - max(a.box[0], b.box[0])
    h = min(a.box[3], b.box[3]) - max(a.box[1], b.box[1])
    if w <= 0 or h <= 0:
        return False
    area = (a.box[2] - a.box[0]) * (a.box[3] - a.box[1])
    return w * h >= 0.5 * area


class PaddleOcrEngine:
    """A PaddleOCR (PP-OCR) detection + recognition pipeline for a specific det/rec
    model pair, on the processor or (`use_device("gpu")`) the graphics card."""

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
        self._pages_read = 0

    def use_device(self, device: str) -> None:
        if device != self._device:
            self._device = device
            self._ocr = None

    @property
    def device(self) -> str:
        return self._device

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

        if self._device == "gpu":
            check_paddle_cuda()
        return PaddleOCR(
            text_detection_model_name=self._det_model_name,
            text_recognition_model_name=self._rec_model_name,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device=paddle_device(self._device),
            # oneDNN is the processor's; on the card it doesn't apply.
            enable_mkldnn=self._device == "cpu",
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
        try:
            result = self._run_strips(image)
        except Exception as exc:
            from docbox.backend.core import gpu

            if self._device != "gpu" or (self._pages_read and not gpu.is_out_of_memory(exc)):
                raise
            self._fall_back(exc)
            result = self._run_strips(image)
        self._pages_read += 1
        return result

    def _fall_back(self, exc: BaseException) -> None:
        """Rebuild on the processor after the graphics card failed, and say why."""
        from docbox.backend.core import gpu

        gpu.record_fallback(self._model_id, gpu.fallback_message(exc))
        self.use_device("cpu")
        self.load()

    def _run_strips(self, image: Image.Image) -> OcrResult:
        strips = _strips(*image.size)
        lines: list[OcrLine] = []
        previous: list[OcrLine] = []  # what the strip before this one kept
        for strip in strips:
            dx, dy = strip[0], strip[1]
            kept: list[OcrLine] = []
            for line in self._run_one(image if len(strips) == 1 else image.crop(strip)):
                if line.box is not None and len(strips) > 1:
                    line.box = [line.box[0] + dx, line.box[1] + dy,
                                line.box[2] + dx, line.box[3] + dy]
                    if not _owned(strip, strips, line.box):
                        continue
                    if any(_same_line(line, other) for other in previous):
                        continue
                kept.append(line)
            lines.extend(kept)
            previous = kept

        return OcrResult(
            model_id=self._model_id,
            lines=lines,
            text="\n".join(line.text for line in lines),
        )

    def _run_one(self, image: Image.Image) -> list[OcrLine]:
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
        return lines

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
