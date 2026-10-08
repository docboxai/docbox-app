"""PDFs built in the test, so no sample files are checked in: pages that carry their own
text (as an exported invoice does), scan-like pages (one image over the whole page), or
both on one page."""

from __future__ import annotations

import io
import zlib
from dataclasses import dataclass, field

from PIL import Image

from docbox.backend.core.pdf_writer import _Builder

# US letter, in points.
PAGE_W, PAGE_H = 612, 792
# Text lines start here (top-left margin) and go down one every LINE_STEP points.
TEXT_X, TEXT_TOP, LINE_STEP, FONT_SIZE = 72, 720, 20, 12


@dataclass
class Page:
    lines: list[str] = field(default_factory=list)
    # Drawn over the whole page, like a scanner's output.
    image: Image.Image | None = None
    # Draw the image through a form XObject, as some PDF producers do.
    image_in_form: bool = False
    rotate: int = 0


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[Page], *, size: tuple[int, int] = (PAGE_W, PAGE_H),
             box_on_tree: bool = False) -> bytes:
    """`box_on_tree` sets the page size once, on the page tree, for every page to inherit
    (as many PDF producers write it) instead of on each page."""
    width, height = size
    box = f"/MediaBox [0 0 {width} {height}]"
    b = _Builder()
    catalog = b.reserve()
    pages_obj = b.reserve()
    font = b.add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                 b"/Encoding /WinAnsiEncoding >>")
    kids = []
    for page in pages:
        ops: list[str] = []
        xobjects: dict[str, int] = {}
        if page.image is not None:
            jpeg = io.BytesIO()
            page.image.convert("RGB").save(jpeg, format="JPEG")
            image = b.add(b.stream(
                f"/Type /XObject /Subtype /Image /Width {page.image.width} "
                f"/Height {page.image.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 "
                f"/Filter /DCTDecode", jpeg.getvalue()))
            if page.image_in_form:
                form = b.add(b.stream(
                    f"/Type /XObject /Subtype /Form /BBox [0 0 1 1] "
                    f"/Resources << /XObject << /Im0 {image} 0 R >> >>",
                    b"q 1 0 0 1 0 0 cm /Im0 Do Q"))
                xobjects["Fm0"] = form
                ops.append(f"q {width} 0 0 {height} 0 0 cm /Fm0 Do Q")
            else:
                xobjects["Im0"] = image
                ops.append(f"q {width} 0 0 {height} 0 0 cm /Im0 Do Q")
        for i, line in enumerate(page.lines):
            ops.append(f"BT /F1 {FONT_SIZE} Tf {TEXT_X} {TEXT_TOP - LINE_STEP * i} Td "
                       f"({_escape(line)}) Tj ET")
        contents = b.add(b.stream("/Filter /FlateDecode", zlib.compress("\n".join(ops).encode())))
        xobj = " ".join(f"/{name} {num} 0 R" for name, num in xobjects.items())
        kids.append(b.add(
            f"<< /Type /Page /Parent {pages_obj} 0 R {'' if box_on_tree else box} "
            f"/Rotate {page.rotate} "
            f"/Resources << /Font << /F1 {font} 0 R >> /XObject << {xobj} >> >> "
            f"/Contents {contents} 0 R >>".encode()))
    b.set(pages_obj, (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                      f"/Count {len(kids)} {box if box_on_tree else ''} >>").encode())
    b.set(catalog, f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode())
    return b.render(catalog)


INVOICE = ["Invoice INV-0312 from Northwind Supply Co.", "Total due $1,284.00 by 31 October"]


def scan() -> Image.Image:
    return Image.new("RGB", (306, 396), "white")
