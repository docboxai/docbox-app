"""OCREngine implementation backed by the `easyocr` package.

Its packages (easyocr + CPU-only PyTorch) are the `easyocr` pyproject extra (or, for the
graphics card, `easyocr-gpu` with PyTorch's CUDA 12.6 build), installed
on demand by `core/runtime.py` before `download()` runs — this module never installs
anything itself, and imports easyocr/numpy lazily so the base install can import it.

`is_downloaded()` is implemented by attempting a real `easyocr.Reader(...,
download_enabled=False)` construction rather than checking for specific cached filenames:
EasyOCR bundles recognition weights per *combination* of requested languages (not a
single stable name per language), so guessing filenames would be fragile. The
constructed `Reader` is cached on success and reused for `run()`.

On the graphics card (`use_device("gpu")`) the Reader gets `gpu=True`. EasyOCR quietly reads
on the processor when PyTorch sees no CUDA device, so `load()` checks first and raises,
letting core/gpu.py fall back with a reason; running out of graphics memory on a page
falls back too. `is_downloaded()`'s check Reader stays on the processor.
"""

from __future__ import annotations

from PIL import Image

from docbox.backend.core.paths import get_models_dir
from docbox.backend.engines.base import ProgressCallback
from docbox.backend.schemas import OcrLine, OcrResult


def _cache_dir():
    d = get_models_dir() / "easyocr"
    d.mkdir(parents=True, exist_ok=True)
    return d


class EasyOcrEngine:
    """EasyOCR reader for a specific language set, on the processor or the graphics card."""

    def __init__(self, *, model_id: str, langs: list[str], device: str = "cpu") -> None:
        self._model_id = model_id
        self._langs = langs
        self._device = device
        self._reader = None

    def use_device(self, device: str) -> None:
        if device != self._device:
            self._device = device
            self._reader = None

    @property
    def device(self) -> str:
        return self._device

    def _try_build_reader(self, *, download_enabled: bool, gpu: bool = False):
        import easyocr

        if gpu:
            import torch

            if not torch.cuda.is_available():
                raise RuntimeError("PyTorch found no CUDA graphics card")
        return easyocr.Reader(
            self._langs,
            gpu=gpu,
            model_storage_directory=str(_cache_dir()),
            download_enabled=download_enabled,
            verbose=False,
        )

    def is_downloaded(self) -> bool:
        if self._reader is not None:
            # Loaded, and kept loaded between reads (engine_cache checks this on every use):
            # building a second Reader to check would hold two in memory. The weights are
            # there unless another process removed the model, which removes them all.
            return any(_cache_dir().glob("*.pth"))
        try:
            self._try_build_reader(download_enabled=False)
        except Exception:  # noqa: BLE001 — package absent, models absent, etc.
            return False
        return True

    def download(self, progress_cb: ProgressCallback) -> None:
        if self.is_downloaded():
            progress_cb(100.0, "already downloaded")
            return

        progress_cb(10.0, f"downloading recognition models for {', '.join(self._langs)}")
        self._reader = self._try_build_reader(download_enabled=True)

        if not self.is_downloaded():
            raise RuntimeError("Model download reported success but models are missing on disk")

        progress_cb(100.0, "ready")

    def load(self) -> None:
        if self._reader is not None:
            return
        if not self.is_downloaded():
            raise RuntimeError("Model is not downloaded yet")
        self._reader = self._try_build_reader(
            download_enabled=False, gpu=self._device == "gpu"
        )

    def run(self, image: Image.Image) -> OcrResult:
        import numpy as np

        if self._reader is None:
            self.load()

        pixels = np.array(image.convert("RGB"))
        try:
            results = self._reader.readtext(pixels)
        except Exception as exc:
            from docbox.backend.core import gpu

            if self._device != "gpu" or not gpu.is_out_of_memory(exc):
                raise
            gpu.record_fallback(self._model_id, gpu.fallback_message(exc))
            self.use_device("cpu")
            self.load()
            results = self._reader.readtext(pixels)

        lines: list[OcrLine] = []
        for bbox, text, confidence in results:
            xs = [float(p[0]) for p in bbox]
            ys = [float(p[1]) for p in bbox]
            box = [min(xs), min(ys), max(xs), max(ys)]
            lines.append(OcrLine(text=text, confidence=float(confidence), box=box))

        return OcrResult(
            model_id=self._model_id,
            lines=lines,
            text="\n".join(line.text for line in lines),
        )

    def delete(self) -> None:
        # The catalog has a single EasyOCR entry, so its weights dir is wholly its own.
        self._reader = None
        for weights in _cache_dir().glob("*.pth"):
            weights.unlink(missing_ok=True)
