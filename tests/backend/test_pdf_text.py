"""Reads take a PDF page's own text instead of OCRing it when the page carries usable text
and isn't a scan (core/pages.py::iter_read_pages); benchmarks still read every page."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
import pytest
from fastapi.testclient import TestClient

from docbox.backend.core import engine_cache
from docbox.backend.core.pages import _PDF_RENDER_DPI, iter_read_pages
from docbox.backend.core.registry import registry
from tests.backend.reading_fakes import read, register
from tests.pdf_samples import (
    FONT_SIZE,
    INVOICE,
    PAGE_H,
    TEXT_TOP,
    TEXT_X,
    Page,
    make_pdf,
    scan,
)


@pytest.fixture(autouse=True)
def _no_warm_engines():
    engine_cache.evict_all()
    yield
    engine_cache.evict_all()


@pytest.fixture()
def two_models(data_dir):
    a = register("test-count-a")
    b = register("test-count-b")
    yield a, b
    for spec, _ in (a, b):
        registry._models.pop(spec.id, None)


# --- a PDF's own text ------------------------------------------------------------------


def test_pdf_pages_with_their_own_text_need_no_model(two_models) -> None:
    (a, stats), _ = two_models
    pdf = make_pdf([Page(lines=INVOICE), Page(lines=["Page two of the report, as exported"])])
    detail = read(a, pdf, "invoice.pdf", "application/pdf")
    assert detail.state == "done"
    assert [p.source for p in detail.pages] == ["pdf_text", "pdf_text"]
    assert detail.pages[0].text == "\n".join(INVOICE)
    assert [ln.text for ln in detail.pages[0].lines] == INVOICE
    assert (stats.loads, stats.runs) == (0, 0)  # the model was never even loaded


def test_own_text_lines_are_placed_like_an_engines(two_models) -> None:
    pages = list(iter_read_pages(make_pdf([Page(lines=INVOICE)]), "application/pdf"))
    first = pages[0].lines[0]
    left, top, right, bottom = first.box
    scale = _PDF_RENDER_DPI / 72
    # Pixels of the page as rendered for OCR, origin top-left: within a glyph's height of
    # where the line was drawn.
    assert abs(left - TEXT_X * scale) < 3 * scale
    assert (PAGE_H - TEXT_TOP - FONT_SIZE) * scale <= top < bottom <= (PAGE_H - TEXT_TOP + 4) * scale
    assert right > left + 100 * scale
    assert pages[0].image is None  # not rendered: nothing needs the picture


def test_scans_and_pages_with_too_little_text_are_read_by_the_model(two_models) -> None:
    (a, stats), _ = two_models
    pdf = make_pdf([
        Page(lines=INVOICE),
        Page(image=scan(), lines=INVOICE),  # a scan with an older OCR layer on top
        Page(lines=["7"]),  # only a page number
        Page(image=scan(), image_in_form=True, lines=INVOICE),
        Page(lines=INVOICE, rotate=90),
    ])
    detail = read(a, pdf, "mixed.pdf", "application/pdf")
    assert [p.source for p in detail.pages] == ["pdf_text", "ocr", "ocr", "ocr", "ocr"]
    assert detail.pages[1].text == "ocr text"
    assert (stats.loads, stats.runs) == (1, 4)


def test_reading_every_page_with_the_model_on_request(two_models) -> None:
    (a, stats), _ = two_models
    detail = read(a, make_pdf([Page(lines=INVOICE)]), "invoice.pdf", "application/pdf",
                  use_pdf_text=False)
    assert [p.source for p in detail.pages] == ["ocr"] and stats.runs == 1


def test_searchable_pdf_from_own_text_keeps_the_page_and_its_text(two_models) -> None:
    (a, _), _ = two_models
    detail = read(a, make_pdf([Page(lines=INVOICE)]), "invoice.pdf", "application/pdf",
                  fmt="pdf")
    out = pdfium.PdfDocument(Path(detail.output_path).read_bytes())
    page = out[0]
    assert "Total due $1,284.00" in page.get_textpage().get_text_range()
    assert any(True for _ in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]))  # the scan


def test_reads_api_takes_the_option(client: TestClient, two_models) -> None:
    def sources(use_pdf_text: str) -> list[str]:
        resp = client.post(
            "/api/reads",
            files=[("files", ("invoice.pdf", make_pdf([Page(lines=INVOICE)]), "application/pdf"))],
            data={"model_id": "test-count-a", "use_pdf_text": use_pdf_text},
        )
        read_id = resp.json()["reads"][0]["id"]
        deadline = time.monotonic() + 10
        while (body := client.get(f"/api/reads/{read_id}").json())["state"] not in (
                "done", "error"):
            assert time.monotonic() < deadline
            time.sleep(0.02)
        return [p["source"] for p in body["pages"]]

    assert sources("true") == ["pdf_text"]
    assert sources("false") == ["ocr"]


def test_benchmarks_read_every_page_with_the_model(fakes, tmp_path) -> None:
    """Benchmarks measure models, so a page's own text never stands in for a model's read."""
    pdf = tmp_path / "exported.pdf"
    pdf.write_bytes(make_pdf([Page(lines=INVOICE)]))
    job = {"model_id": "fake-good", "files": [{"id": "exported.pdf", "path": str(pdf)}]}
    proc = subprocess.run([sys.executable, "-m", "docbox.benchmark.worker"],
                          input=json.dumps(job), capture_output=True, text=True,
                          env=os.environ.copy(), timeout=60, check=False)
    pages = [e for e in map(json.loads, proc.stdout.splitlines()) if e["event"] == "page"]
    # The fake engine reads a white page as no text; the PDF's own text would be INVOICE.
    assert len(pages) == 1 and pages[0]["text"] == ""
