"""A minimal searchable-PDF writer: each page is the scanned image with the recognized
text laid over it invisibly (text render mode 3), so the PDF looks like the original but
can be searched, selected and copied.

The text uses the same trick as Tesseract's own PDF renderer: a "glyphless" TrueType
font whose one glyph is empty, addressed with two-byte codes equal to the text's UTF-16
code units (Identity-H), plus a ToUnicode map that turns those codes back into the
original characters. That covers every script without embedding real fonts. Lines with a
position (`OcrLine.box`) are stretched over their spot on the page; lines without one
(vision-language engines don't report positions) are stacked down the page in reading
order, which keeps them searchable but not aligned with the image.
"""

from __future__ import annotations

import base64
import io
import zlib
from dataclasses import dataclass

from PIL import Image

from docbox.backend.schemas import OcrLine

# Tesseract's pdf.ttf (Apache-2.0, https://github.com/tesseract-ocr/tesseract): a font
# with a single empty glyph that advances half an em.
_GLYPHLESS_TTF = base64.b64decode(
    "AAEAAAAKAIAAAwAgT1MvMlbeyJQAAAEoAAAAYGNtYXAACgA0AAABkAAAAB5nbHlmFSJBJAAAAbgAAAAYaGVhZAt4"
    "8WUAAACsAAAANmhoZWEMAgQCAAAA5AAAACRobXR4BAAAAAAAAYgAAAAIbG9jYQAMAAAAAAGwAAAABm1heHAABAAF"
    "AAABCAAAACBuYW1l8usW2gAAAdAAAABLcG9zdAABAAEAAAIcAAAAIAABAAAAAQAAsJRxEF8PPPUEBwgAAAAAAM+a"
    "/G4AAAAA1MOn8gAAAAAEAAgAAAAAEAACAAAAAAAAAAEAAAgA//8AAAQAAAAAAAQAAAEAAAAAAAAAAAAAAAAAAAAC"
    "AAEAAAACAAQAAQAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAwAAAZAABQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAUA"
    "AQABAAAAAAAAAAAAAAAAAAAAAAAAAAAAR09PRwBAAAAAAAAB//8AAAABAAGAAAAAAAAAAAAAAAAAAAABAAAAAAAA"
    "BAAAAAAAAAIAAQAAAAAAFAADAAAAAAAUAAYACgAAAAAAAAAAAAAAAAAMAAAAAQAAAAAEAAgAAAMAADEhESEEAPwA"
    "CAAAAAADACoAAAADAAAABQAWAAAAAQAAAAAABQALABYAAwABBAkABQAWAAAAVgBlAHIAcwBpAG8AbgAgADEALgAw"
    "VmVyc2lvbiAxLjAAAAEAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAA="
)
_GLYPH_ADVANCE = 0.5  # in ems; matches /DW 500 below
_JPEG_QUALITY = 85


@dataclass
class PdfPage:
    image: Image.Image
    dpi: float
    lines: list[OcrLine]


def _to_unicode_cmap() -> bytes:
    # Each code maps to the same UTF-16 code unit. Split into 256 ranges because a
    # bfrange may only vary in its last byte.
    ranges = "\n".join(f"<{hi:02X}00> <{hi:02X}FF> <{hi:02X}00>" for hi in range(256))
    return (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        f"256 beginbfrange\n{ranges}\nendbfrange\n"
        "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    ).encode("ascii")


def _hex_utf16(text: str) -> str:
    return text.encode("utf-16-be").hex().upper()


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def _text_ops(page: PdfPage, width_pt: float, height_pt: float) -> list[str]:
    scale = 72.0 / page.dpi
    lines = [line for line in page.lines if line.text.strip()]
    unplaced = [line for line in lines if not line.box]
    step = min(14.0, height_pt / (len(unplaced) + 1)) if unplaced else 0.0
    ops: list[str] = []
    next_y = height_pt - step
    for line in lines:
        text = line.text.strip()
        units = len(text.encode("utf-16-be")) // 2
        if line.box:
            left, top, right, bottom = line.box
            x, y = left * scale, height_pt - bottom * scale
            size = max(1.0, (bottom - top) * scale)
            width = max(1.0, (right - left) * scale)
        else:
            x, y, size, width = 18.0, next_y, max(1.0, step * 0.8), width_pt - 36.0
            next_y -= step
        stretch = 100.0 * width / max(1e-6, units * size * _GLYPH_ADVANCE)
        ops.append(
            f"BT 3 Tr /F1 {_fmt(size)} Tf {_fmt(stretch)} Tz "
            f"1 0 0 1 {_fmt(x)} {_fmt(y)} Tm <{_hex_utf16(text)}> Tj ET"
        )
    return ops


class _Builder:
    def __init__(self) -> None:
        self.objects: list[bytes] = []

    def reserve(self) -> int:
        self.objects.append(b"")
        return len(self.objects)

    def set(self, num: int, body: bytes) -> None:
        self.objects[num - 1] = body

    def add(self, body: bytes) -> int:
        num = self.reserve()
        self.set(num, body)
        return num

    def stream(self, header: str, data: bytes) -> bytes:
        return (
            f"<< {header} /Length {len(data)} >>\nstream\n".encode("ascii")
            + data
            + b"\nendstream"
        )

    def render(self, root: int) -> bytes:
        out = io.BytesIO()
        out.write(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for num, body in enumerate(self.objects, start=1):
            offsets.append(out.tell())
            out.write(f"{num} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
        xref = out.tell()
        out.write(f"xref\n0 {len(self.objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
        for offset in offsets:
            out.write(f"{offset:010d} 00000 n \n".encode("ascii"))
        out.write(
            f"trailer\n<< /Size {len(self.objects) + 1} /Root {root} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n".encode("ascii")
        )
        return out.getvalue()


def write_searchable_pdf(pages: list[PdfPage]) -> bytes:
    b = _Builder()
    catalog = b.reserve()
    pages_obj = b.reserve()

    font_file = b.add(b.stream(f"/Length1 {len(_GLYPHLESS_TTF)}", _GLYPHLESS_TTF))
    descriptor = b.add(
        f"<< /Type /FontDescriptor /FontName /GlyphLessFont /Flags 5 "
        f"/FontBBox [0 0 {int(1000 * _GLYPH_ADVANCE)} 1000] /ItalicAngle 0 /Ascent 1000 "
        f"/Descent 0 /CapHeight 1000 /StemV 80 /FontFile2 {font_file} 0 R >>".encode("ascii")
    )
    # Every code (CID) draws glyph 1, the empty one.
    cid_to_gid = zlib.compress(b"\x00\x01" * 65536)
    cid_map = b.add(b.stream("/Filter /FlateDecode", cid_to_gid))
    cid_font = b.add(
        f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /GlyphLessFont "
        f"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        f"/FontDescriptor {descriptor} 0 R /DW {int(1000 * _GLYPH_ADVANCE)} "
        f"/CIDToGIDMap {cid_map} 0 R >>".encode("ascii")
    )
    to_unicode = b.add(b.stream("/Filter /FlateDecode", zlib.compress(_to_unicode_cmap())))
    font = b.add(
        f"<< /Type /Font /Subtype /Type0 /BaseFont /GlyphLessFont /Encoding /Identity-H "
        f"/DescendantFonts [{cid_font} 0 R] /ToUnicode {to_unicode} 0 R >>".encode("ascii")
    )

    kids: list[int] = []
    for page in pages:
        width_pt = page.image.width * 72.0 / page.dpi
        height_pt = page.image.height * 72.0 / page.dpi
        jpeg = io.BytesIO()
        page.image.convert("RGB").save(jpeg, format="JPEG", quality=_JPEG_QUALITY)
        image = b.add(b.stream(
            f"/Type /XObject /Subtype /Image /Width {page.image.width} "
            f"/Height {page.image.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 "
            f"/Filter /DCTDecode",
            jpeg.getvalue(),
        ))
        ops = [f"q {_fmt(width_pt)} 0 0 {_fmt(height_pt)} 0 0 cm /Im0 Do Q"]
        ops += _text_ops(page, width_pt, height_pt)
        contents = b.add(b.stream("/Filter /FlateDecode", zlib.compress("\n".join(ops).encode())))
        kids.append(b.add(
            f"<< /Type /Page /Parent {pages_obj} 0 R "
            f"/MediaBox [0 0 {_fmt(width_pt)} {_fmt(height_pt)}] "
            f"/Resources << /Font << /F1 {font} 0 R >> /XObject << /Im0 {image} 0 R >> >> "
            f"/Contents {contents} 0 R >>".encode("ascii")
        ))

    b.set(pages_obj, (
        f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    ).encode("ascii"))
    b.set(catalog, f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode("ascii"))
    return b.render(catalog)
