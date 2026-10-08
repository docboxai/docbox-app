"""PDFium isn't thread-safe: two threads in it at once corrupt its memory and kill the
process. The reader thread, MCP tools (start_read beside read_file) and /api/ocr/run all open
PDFs, so every call into it goes through one lock (core/pages.py::_PDFIUM_LOCK)."""

from __future__ import annotations

import threading
import time

import pypdfium2 as pdfium

from docbox.backend.core.pages import count_pages, iter_pages, iter_read_pages, load_page
from tests.pdf_samples import INVOICE, Page, make_pdf, scan


def test_pdfium_is_never_entered_by_two_threads_at_once(monkeypatch) -> None:
    inside = 0
    overlaps: list[str] = []
    counting = threading.Lock()

    def watched(name, fn):
        def call(*args, **kwargs):
            nonlocal inside
            with counting:
                inside += 1
                if inside > 1:
                    overlaps.append(name)
            try:
                time.sleep(0.002)  # widen the window another thread could slip into
                return fn(*args, **kwargs)
            finally:
                with counting:
                    inside -= 1
        return call

    for cls, name in ((pdfium.PdfDocument, "__len__"), (pdfium.PdfDocument, "get_page"),
                      (pdfium.PdfPage, "render"), (pdfium.PdfPage, "get_textpage")):
        monkeypatch.setattr(cls, name, watched(name, getattr(cls, name)))

    text_pdf = make_pdf([Page(lines=INVOICE), Page(image=scan(), lines=INVOICE)])
    scan_pdf = make_pdf([Page(image=scan())] * 2)
    errors: list[BaseException] = []

    def repeat(work):
        def loop() -> None:
            try:
                for _ in range(3):
                    work()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
        return threading.Thread(target=loop)

    threads = [
        repeat(lambda: list(iter_read_pages(text_pdf, "application/pdf", keep_images=True))),
        repeat(lambda: list(iter_pages(scan_pdf, "application/pdf"))),
        repeat(lambda: (count_pages(text_pdf, "application/pdf"),
                        load_page(scan_pdf, "application/pdf", 1))),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert overlaps == []
