from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from docbox.backend.core import engine_cache
from docbox.backend.core.pages import PageError, load_page
from docbox.backend.core.reader import NotRunnable, check_runnable
from docbox.backend.engines.remote_engine import EngineServiceError
from docbox.backend.schemas import OcrResult

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


# One page, answered directly. The app reads whole files through /api/reads; this stays
# as the contract RemoteEngine speaks to engine containers (engines/remote_engine.py),
# which send a document's pages one request at a time: the engine stays loaded between
# them (core/engine_cache.py), and requests take turns on it.
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

    data = file.file.read()
    try:
        image = load_page(data, file.content_type, page)
    except PageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    try:
        with engine_cache.loaded(spec) as engine:
            return engine.run(image)
    except engine_cache.NotDownloaded:
        raise HTTPException(
            status_code=409, detail=f"Model '{model_id}' is not downloaded yet"
        ) from None
    except EngineServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
