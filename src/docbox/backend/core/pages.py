"""Turning an uploaded file into page images: every page of a PDF or multi-page TIFF,
or the single image otherwise. For reads, a PDF page that already carries its text (an
exported invoice, a report saved from a word processor) can give that text instead of an
image to OCR."""

from __future__ import annotations

import io
import threading
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageSequence

from docbox.backend.schemas import OcrLine

_PDF_RENDER_DPI = 200
# PDFium isn't thread-safe, and pypdfium2 lets go of the GIL inside it: two threads in it at
# once (a background read beside an MCP read_file, the reader beside /api/ocr/run) corrupt
# its memory and kill the process. Every call into it holds this lock, and pages and bitmaps
# are closed while holding it rather than left to finalizers, which run on any thread.
# Reentrant: garbage collection can close an abandoned page iterator inside a locked section.
_PDFIUM_LOCK = threading.RLock()
# A page's own text replaces OCR only when there's clearly some: a lone page number or a
# stamp on a scanned page shouldn't stop the page from being read.
_MIN_TEXT_CHARS = 20
# ...and only when images cover at most half of the page. A scan is an image, often with
# an older OCR layer of unknown quality on top; those pages are read again.
_MAX_IMAGE_COVER = 0.5
# ...and only when it reads as text. A font embedded without a proper character map
# extracts as private-use, replacement or control characters; at most this share of
# those, or the page is OCRed.
_MAX_UNREADABLE_SHARE = 0.1


class PageError(ValueError):
    """The file can't be read as a document, or has no such page."""


@dataclass
class Page:
    image: Image.Image
    # Pixels per inch, so a searchable PDF can give the page its real paper size.
    dpi: float


def is_pdf(content_type: str | None, file_name: str | None = None) -> bool:
    return content_type == "application/pdf" or (file_name or "").lower().endswith(".pdf")


def _image_dpi(image: Image.Image) -> float:
    dpi = image.info.get("dpi")
    if dpi and dpi[0] and float(dpi[0]) >= 50:
        return float(dpi[0])
    # No resolution recorded (screenshots, phone photos): size the page as if it were
    # letter-width paper rather than a poster-sized sheet at 72 ppi.
    return max(72.0, image.width / 8.5)


def _open_image(data: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise PageError(f"Could not read image: {exc}") from None


def _open_pdf(data: bytes):
    """Call with `_PDFIUM_LOCK` held."""
    import pypdfium2 as pdfium

    try:
        return pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise PageError(f"Could not read PDF: {exc}") from None


def _render(page) -> Image.Image:
    """Call with `_PDFIUM_LOCK` held. The image is a copy, so the bitmap can go."""
    bitmap = page.render(scale=_PDF_RENDER_DPI / 72)
    try:
        return bitmap.to_pil().convert("RGB")
    finally:
        bitmap.close()


def _each_pdf_page[T](data: bytes, use: Callable[[Any], T]) -> Iterator[T]:
    """`use(page)` for every page of a PDF in order, each call holding `_PDFIUM_LOCK`; the
    results are yielded with it released, so other threads get PDFium between pages."""
    with _PDFIUM_LOCK:
        pdf = _open_pdf(data)
    try:
        with _PDFIUM_LOCK:
            count = len(pdf)
        for index in range(count):
            with _PDFIUM_LOCK:
                page = pdf[index]
                try:
                    result = use(page)
                finally:
                    page.close()
            yield result
    finally:
        with _PDFIUM_LOCK:
            pdf.close()


def count_pages(data: bytes, content_type: str | None, file_name: str | None = None) -> int:
    if is_pdf(content_type, file_name):
        with _PDFIUM_LOCK:
            pdf = _open_pdf(data)
            try:
                return len(pdf)
            finally:
                pdf.close()
    return getattr(_open_image(data), "n_frames", 1)


def iter_pages(
    data: bytes, content_type: str | None, file_name: str | None = None
) -> Iterator[Page]:
    """Yield every page in order. Rendering is lazy, so a long PDF never sits in memory
    as a stack of full-resolution images."""
    if is_pdf(content_type, file_name):
        for image in _each_pdf_page(data, _render):
            yield Page(image, _PDF_RENDER_DPI)
        return

    image = _open_image(data)
    for frame in ImageSequence.Iterator(image):
        yield Page(frame.convert("RGB"), _image_dpi(image))


@dataclass
class ReadablePage:
    """A page as a read takes it: an image to OCR, or (`lines` set) the PDF's own text,
    with `image` then only when the output still needs it (a searchable PDF)."""

    image: Image.Image | None
    dpi: float
    # The page's own text lines, boxed in the rendered image's pixels like an engine's.
    lines: list[OcrLine] | None = None
    text: str = ""


def iter_read_pages(
    data: bytes, content_type: str | None, file_name: str | None = None, *,
    use_pdf_text: bool = True, keep_images: bool = False,
) -> Iterator[ReadablePage]:
    """Every page in order, for a read. With `use_pdf_text`, a PDF page with usable text of
    its own comes with that text, and is only rendered when `keep_images` asks for it.
    Benchmarks don't use this: they measure models, so every page goes through OCR."""
    if not (use_pdf_text and is_pdf(content_type, file_name)):
        for page in iter_pages(data, content_type, file_name):
            yield ReadablePage(page.image, page.dpi)
        return

    def read(page) -> ReadablePage:
        own = _own_text(page)
        image = _render(page) if own is None or keep_images else None
        if own is None:
            return ReadablePage(image, _PDF_RENDER_DPI)
        text, lines = own
        return ReadablePage(image, _PDF_RENDER_DPI, lines=lines, text=text)

    yield from _each_pdf_page(data, read)


def readable_text(text: str) -> bool:
    """Enough characters (`_MIN_TEXT_CHARS`), nearly all of them real text rather than
    what a font without a character map extracts as."""
    visible = [c for c in text if not c.isspace()]
    if len(visible) < _MIN_TEXT_CHARS:
        return False
    unreadable = sum(
        1 for c in visible if c == "\ufffd" or unicodedata.category(c) in ("Co", "Cn", "Cc", "Cs")
    )
    return unreadable <= _MAX_UNREADABLE_SHARE * len(visible)


def _own_text(page) -> tuple[str, list[OcrLine]] | None:
    """The page's text and its lines, when the page has usable text and isn't a scan;
    None when it should be OCRed. Call with `_PDFIUM_LOCK` held."""
    import pypdfium2.raw as pdfium_c

    # Rotated pages are left to OCR rather than turning the text boxes with the page.
    if page.get_rotation() % 360:
        return None
    left, bottom, right, top = page.get_cropbox()
    if right <= left or top <= bottom:
        return None

    covered = 0.0
    for obj in page.get_objects(max_depth=1):
        is_image = obj.type == pdfium_c.FPDF_PAGEOBJ_IMAGE
        # An image inside a form XObject reports its bounds in the form's own space, so
        # the form's page-space bounds stand in for it (a conservative overestimate).
        if not is_image and obj.type == pdfium_c.FPDF_PAGEOBJ_FORM:
            is_image = next(
                page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], form=obj, level=1),
                None,
            ) is not None
        if is_image:
            ol, ob, orr, ot = obj.get_bounds()
            covered += max(0.0, min(orr, right) - max(ol, left)) * max(
                0.0, min(ot, top) - max(ob, bottom))
    if covered > _MAX_IMAGE_COVER * (right - left) * (top - bottom):
        return None

    textpage = page.get_textpage()
    try:
        text = textpage.get_text_range().replace("\r\n", "\n").replace("\r", "\n").strip()
        if not readable_text(text):
            return None
        # pdfium groups the characters into one rectangle per run of a line; each becomes
        # a line, placed where the rendered page shows it.
        scale = _PDF_RENDER_DPI / 72
        lines = []
        for i in range(textpage.count_rects()):
            rl, rb, rr, rt = textpage.get_rect(i)
            line = textpage.get_text_bounded(rl, rb, rr, rt).strip()
            if line:
                lines.append(OcrLine(text=line, box=[
                    (rl - left) * scale, (top - rt) * scale, (rr - left) * scale, (top - rb) * scale,
                ]))
    finally:
        textpage.close()
    return text, lines


def load_page(data: bytes, content_type: str | None, page: int) -> Image.Image:
    """One page, for the single-page `/api/ocr/run` route."""
    if page < 0:
        raise PageError(f"There is no page {page}")
    if is_pdf(content_type):
        with _PDFIUM_LOCK:
            pdf = _open_pdf(data)
            try:
                if page >= len(pdf):
                    raise PageError(f"PDF has no page {page}")
                # Closing the document closes the page too.
                return _render(pdf[page])
            finally:
                pdf.close()
    for index, item in enumerate(iter_pages(data, content_type)):
        if index == page:
            return item.image
    raise PageError(f"The file has no page {page}")
