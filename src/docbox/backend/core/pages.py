"""Turning an uploaded file into page images: every page of a PDF or multi-page TIFF,
or the single image otherwise."""

from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass

from PIL import Image, ImageSequence

_PDF_RENDER_DPI = 200


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


def count_pages(data: bytes, content_type: str | None, file_name: str | None = None) -> int:
    if is_pdf(content_type, file_name):
        import pypdfium2 as pdfium

        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            raise PageError(f"Could not read PDF: {exc}") from None
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
        import pypdfium2 as pdfium

        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            raise PageError(f"Could not read PDF: {exc}") from None
        try:
            for index in range(len(pdf)):
                bitmap = pdf[index].render(scale=_PDF_RENDER_DPI / 72)
                yield Page(bitmap.to_pil().convert("RGB"), _PDF_RENDER_DPI)
        finally:
            pdf.close()
        return

    image = _open_image(data)
    for frame in ImageSequence.Iterator(image):
        yield Page(frame.convert("RGB"), _image_dpi(image))


def load_page(data: bytes, content_type: str | None, page: int) -> Image.Image:
    """One page, for the single-page `/api/ocr/run` route."""
    if page < 0:
        raise PageError(f"There is no page {page}")
    if is_pdf(content_type):
        import pypdfium2 as pdfium

        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            raise PageError(f"Could not read PDF: {exc}") from None
        try:
            if page >= len(pdf):
                raise PageError(f"PDF has no page {page}")
            return pdf[page].render(scale=_PDF_RENDER_DPI / 72).to_pil().convert("RGB")
        finally:
            pdf.close()
    for index, item in enumerate(iter_pages(data, content_type)):
        if index == page:
            return item.image
    raise PageError(f"The file has no page {page}")
