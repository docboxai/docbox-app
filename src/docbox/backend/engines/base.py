"""Common interface every OCR engine implementation must satisfy."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PIL import Image

from docbox.backend.schemas import OcrResult

# Progress callback: (progress_pct in [0, 100], human-readable stage message) -> None
ProgressCallback = Callable[[float, str], None]


class OCREngine(Protocol):
    """A runnable OCR backend for one specific model.

    `device` is threaded through engine factories today only as a forward-compatible
    slot (currently always "cpu"); v1 does not implement GPU acceleration.

    An engine whose model runs in another program's process (Ollama, a cloud API, an
    engine container) sets the class attribute `runs_in_process = False`: the memory a
    benchmark measures around it would be DocBox's own, not the model's.
    """

    def is_downloaded(self) -> bool: ...

    def download(self, progress_cb: ProgressCallback) -> None: ...

    def load(self) -> None: ...

    def run(self, image: Image.Image) -> OcrResult: ...

    def delete(self) -> None:
        """Remove this model's downloaded files. Raise NotDeletableError if it has none."""
        ...


class NotDeletableError(Exception):
    """The model isn't stored locally (e.g. a cloud model), so there's nothing to delete."""
