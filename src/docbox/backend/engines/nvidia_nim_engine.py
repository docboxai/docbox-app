"""OCREngine implementation that calls an NVIDIA NIM vision-language model over the
network via NVIDIA's OpenAI-compatible API catalog (integrate.api.nvidia.com).

This is the one engine in DocBox that is NOT local-only: the image you run OCR on is
sent to NVIDIA's cloud API using an API key you provide yourself. It's never used
implicitly — a model only appears in the catalog once the user has entered an API key in
the Platforms view, and every model card for it is labeled as a cloud call in the UI.

NVIDIA's inline `image_url` data-URL payloads have an undocumented-in-detail but
real practical size ceiling on the hosted API catalog; large images are downscaled/
recompressed here to stay well under it rather than implementing NVIDIA's separate
large-asset upload flow (out of scope, and its exact contract wasn't verified against
current docs — better to keep this honestly simple than guess at an unverified API).
"""

from __future__ import annotations

import base64
import io

import requests
from PIL import Image

from docbox.backend.core import config_store
from docbox.backend.engines.base import NotDeletableError, ProgressCallback
from docbox.backend.schemas import OcrLine, OcrResult

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"

_OCR_PROMPT = (
    "Transcribe all text visible in this image verbatim, preserving line breaks. "
    "Output only the transcribed text, with no commentary, preamble, or markdown "
    "formatting."
)

_MAX_DIMENSION = 1568  # keeps the encoded payload comfortably under NIM's inline limit
_JPEG_QUALITY = 85


def _image_to_data_url(image: Image.Image) -> str:
    img = image.convert("RGB")
    if max(img.size) > _MAX_DIMENSION:
        img.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_JPEG_QUALITY)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


class NvidiaNimOcrEngine:
    """Runs OCR-style transcription through an NVIDIA-hosted vision-language model."""

    # The model runs on NVIDIA's servers (see base.py).
    runs_in_process = False

    def __init__(self, *, model_id: str, nim_model: str) -> None:
        self._model_id = model_id
        self._nim_model = nim_model

    def is_downloaded(self) -> bool:
        # Nothing local to download — "ready" means an API key is on file.
        return config_store.get_nvidia_api_key() is not None

    def download(self, progress_cb: ProgressCallback) -> None:
        if config_store.get_nvidia_api_key() is None:
            raise RuntimeError(
                "No NVIDIA API key configured. Add one in the Platforms view "
                "(get one at https://build.nvidia.com), then refresh."
            )
        progress_cb(100.0, "API key configured")

    def load(self) -> None:
        pass

    def delete(self) -> None:
        raise NotDeletableError(
            "NVIDIA NIM models run in NVIDIA's cloud, so nothing is stored locally. "
            "Remove your API key in the Platforms tab to disconnect."
        )

    def run(self, image: Image.Image) -> OcrResult:
        api_key = config_store.get_nvidia_api_key()
        if not api_key:
            raise RuntimeError("No NVIDIA API key configured — add one in the Platforms view.")

        payload = {
            "model": self._nim_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _OCR_PROMPT},
                        {"type": "image_url", "image_url": {"url": _image_to_data_url(image)}},
                    ],
                }
            ],
            "max_tokens": 2048,
            "temperature": 0.0,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            resp = requests.post(
                f"{NIM_BASE_URL}/chat/completions", json=payload, headers=headers, timeout=60
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            detail = getattr(exc.response, "text", "") if exc.response is not None else ""
            raise RuntimeError(f"NVIDIA NIM request failed: {exc} {detail}".strip()) from None

        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        lines = [OcrLine(text=line, confidence=None) for line in text.splitlines() if line.strip()]
        return OcrResult(model_id=self._model_id, lines=lines, text=text)
