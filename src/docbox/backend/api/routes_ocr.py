from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from docbox.backend.core.pages import PageError, load_page
from docbox.backend.core.reader import NotRunnable, check_runnable
from docbox.backend.engines.remote_engine import EngineServiceError
from docbox.backend.schemas import OcrResult

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


# One page, answered directly. The app reads whole files through /api/reads; this stays
# as the contract RemoteEngine speaks to engine containers (engines/remote_engine.py).
@router.post("/run", response_model=OcrResult)
def run_ocr(
    file: UploadFile = File(...),
    model_id: str = Form(...),
    page: int = Form(0),
) -> OcrResult:
    try:
        spec = check_runnable(model_id)
    except NotRunnable as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    engine = spec.engine_factory()
    try:
        if not engine.is_downloaded():
            raise HTTPException(
                status_code=409, detail=f"Model '{model_id}' is not downloaded yet"
            )

        data = file.file.read()
        try:
            image = load_page(data, file.content_type, page)
        except PageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

        engine.load()
        return engine.run(image)
    except EngineServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
