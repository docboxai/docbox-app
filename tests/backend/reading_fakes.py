"""A counting fake engine for read tests: how often a model was loaded and run, whether two
runs overlapped, and a gate that holds a read in the middle of a page."""

from __future__ import annotations

import io
import threading
import time

from PIL import Image

from docbox.backend.core import history, reader
from docbox.backend.core.registry import ModelSpec, registry
from docbox.backend.schemas import OcrLine, OcrResult


class Stats:
    def __init__(self) -> None:
        self.loads = self.runs = self.active = self.max_active = self.deletes = 0
        self.downloaded = True
        self.fail_load = False
        self.run_delay = 0.0
        # When set, run() waits for it: a read that's still going.
        self.gate: threading.Event | None = None
        self.running = threading.Event()
        self.lock = threading.Lock()


class CountingEngine:
    """Counts loads and runs; reads every page as one line, "ocr text"."""

    def __init__(self, stats: Stats) -> None:
        self.stats = stats

    def is_downloaded(self) -> bool:
        return self.stats.downloaded

    def download(self, progress_cb) -> None:
        self.stats.downloaded = True

    def load(self) -> None:
        self.stats.loads += 1
        if self.stats.fail_load:
            raise RuntimeError("weights are corrupt")

    def run(self, image):
        with self.stats.lock:
            self.stats.active += 1
            self.stats.max_active = max(self.stats.max_active, self.stats.active)
        self.stats.running.set()
        if self.stats.gate is not None:
            self.stats.gate.wait(10)
        time.sleep(self.stats.run_delay)
        with self.stats.lock:
            self.stats.active -= 1
            self.stats.runs += 1
        line = OcrLine(text="ocr text", confidence=0.9, box=[1, 1, 60, 12])
        return OcrResult(model_id="counting", lines=[line], text=line.text)

    def delete(self) -> None:
        self.stats.deletes += 1
        self.stats.downloaded = False


def register(model_id: str) -> tuple[ModelSpec, Stats]:
    stats = Stats()
    spec = ModelSpec(
        id=model_id, name=f"Counting {model_id}", engine="fake", description="test double",
        languages=["en"], approx_download_mb=1, approx_ram_mb=1, min_disk_mb=1,
        engine_factory=lambda: CountingEngine(stats),
    )
    registry.register(spec)
    return spec, stats


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (120, 60), "white").save(buf, format="PNG")
    return buf.getvalue()


def read(spec: ModelSpec, data: bytes, name: str = "scan.png", ctype: str = "image/png",
         fmt: str = "txt", use_pdf_text: bool = True):
    """Read one file now, as the CLI does, and return its history detail."""
    read_id = reader.read_now(file_name=name, data=data, content_type=ctype, spec=spec,
                              output_format=fmt, use_pdf_text=use_pdf_text)
    return history.get_detail(read_id)
