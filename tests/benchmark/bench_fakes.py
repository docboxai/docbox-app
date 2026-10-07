"""Fake OCR models for benchmark tests, registered both in the test process and (through
DOCBOX_PRELOAD) in each benchmark worker process.

A page's text is chosen by its grey level, so multi-page files get different text per
page: page n is drawn at grey 20 * n and reads as TEXTS[n]."""

from __future__ import annotations

import os
import time
from pathlib import Path

from PIL import Image

from docbox.backend.core.registry import ModelSpec, registry
from docbox.backend.schemas import OcrLine, OcrResult

TEXTS = {1: "Total due $1,284.00\nRef INV-0312", 2: "Northwind Supply Co.\nPage two"}


def page_image(n: int) -> Image.Image:
    return Image.new("L", (120, 60), color=20 * n)


def _page_no(image: Image.Image) -> int:
    return max(1, round(image.convert("L").getpixel((60, 30)) / 20))


def _sloppy(text: str) -> str:
    return text.replace("1,284", "1,2B4").replace("0312", "O312")


class FakeEngine:
    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour

    def _marker(self) -> Path:
        return Path(os.environ["DOCBOX_DATA_DIR"]) / "models" / f"{self.behaviour}.marker"

    def is_downloaded(self) -> bool:
        return self.behaviour != "notinstalled" or self._marker().exists()

    def download(self, progress_cb) -> None:
        self._marker().parent.mkdir(parents=True, exist_ok=True)
        self._marker().write_text("ok")
        progress_cb(100.0, "done")

    def load(self) -> None:
        if self.behaviour == "brokenload":
            raise RuntimeError("weights are corrupt")
        if self.behaviour == "noisy":
            print("library chatter on stdout")  # must not break the event stream

    def run(self, image: Image.Image) -> OcrResult:
        if self.behaviour == "crash":
            os._exit(3)
        if self.behaviour == "hang":
            time.sleep(3600)
        text = TEXTS.get(_page_no(image), "")
        if self.behaviour == "sloppy":
            text = _sloppy(text)
        conf = 0.6 if self.behaviour == "sloppy" else 0.95
        return OcrResult(model_id=f"fake-{self.behaviour}",
                         lines=[OcrLine(text=t, confidence=conf) for t in text.split("\n")],
                         text=text)

    def delete(self) -> None:
        self._marker().unlink(missing_ok=True)


BEHAVIOURS = ("good", "sloppy", "crash", "hang", "brokenload", "notinstalled", "noisy")


def register() -> None:
    for b in BEHAVIOURS:
        registry.register(ModelSpec(
            id=f"fake-{b}", name=f"Fake {b}", engine="fake", description="test double",
            languages=["en"], approx_download_mb=1, approx_ram_mb=1, min_disk_mb=1,
            engine_factory=lambda b=b: FakeEngine(b),
        ))


def unregister() -> None:
    for b in BEHAVIOURS:
        registry._models.pop(f"fake-{b}", None)


register()
