from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from docbox.backend.core.registry import registry


def _sample_image_bytes() -> bytes:
    img = Image.new("RGB", (400, 100), "white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 30), "Hello DocBox OCR", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_run_ocr_unknown_model_is_404(client: TestClient) -> None:
    resp = client.post(
        "/api/ocr/run",
        files={"file": ("test.png", _sample_image_bytes(), "image/png")},
        data={"model_id": "does-not-exist", "page": "0"},
    )
    assert resp.status_code == 404


@pytest.mark.real_data_dir
def test_run_ocr_recognizes_text(client: TestClient) -> None:
    spec = registry.get("paddleocr-mobile-en")
    if not spec.engine_factory().is_downloaded():
        pytest.skip("paddleocr-mobile-en is not downloaded in this environment")

    resp = client.post(
        "/api/ocr/run",
        files={"file": ("test.png", _sample_image_bytes(), "image/png")},
        data={"model_id": "paddleocr-mobile-en", "page": "0"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["model_id"] == "paddleocr-mobile-en"
    assert len(body["lines"]) >= 1
    assert "docbox" in body["text"].lower()
