from __future__ import annotations

import io

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image

from docbox.backend import platforms
from docbox.backend.core import prerequisites, runtime
from docbox.backend.engines.remote_engine import EngineServiceError
from docbox.backend.schemas import OcrResult

router = APIRouter(prefix="/api/ocr", tags=["ocr"])

_PDF_CONTENT_TYPES = {"application/pdf"}


def _load_image(data: bytes, content_type: str | None, page: int) -> Image.Image:
    if content_type in _PDF_CONTENT_TYPES:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(data)
        try:
            if page < 0 or page >= len(pdf):
                raise HTTPException(status_code=400, detail=f"PDF has no page {page}")
            bitmap = pdf[page].render(scale=200 / 72)
            return bitmap.to_pil().convert("RGB")
        finally:
            pdf.close()

    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not read image: {exc}") from None


@router.post("/run", response_model=OcrResult)
def run_ocr(
    file: UploadFile = File(...),
    model_id: str = Form(...),
    page: int = Form(0),
) -> OcrResult:
    try:
        spec = platforms.resolve_spec(model_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}") from None

    if spec.requires_extra and not runtime.extra_installed(spec.requires_extra):
        raise HTTPException(
            status_code=409,
            detail=f"The {runtime.EXTRAS[spec.requires_extra][0]} isn't installed yet",
        )
    if spec.prerequisite and not prerequisites.is_satisfied(spec.prerequisite):
        name = prerequisites.PREREQUISITES[spec.prerequisite]["name"]
        raise HTTPException(status_code=409, detail=f"{name} needs to be installed and running")

    engine = spec.engine_factory()
    try:
        if not engine.is_downloaded():
            raise HTTPException(
                status_code=409, detail=f"Model '{model_id}' is not downloaded yet"
            )

        data = file.file.read()
        image = _load_image(data, file.content_type, page)

        engine.load()
        return engine.run(image)
    except EngineServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
