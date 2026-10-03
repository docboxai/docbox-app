"""OCREngine implementation that delegates to another DocBox backend instance over HTTP.

Used to split heavy engine families (PaddleOCR, PaddleOCR-VL, Tesseract, EasyOCR) into
their own containers instead of bundling every engine's dependencies into one image —
see docker-compose.yml. Each engine container runs the exact same
`docbox.backend.main:app` as the orchestrator; this class just speaks the same
`/api/models/{id}`, `/api/models/{id}/download`, `/api/ocr/run` HTTP contract those
routes already expose (`routes_models.py`, `routes_ocr.py`) instead of running the
engine in-process. `models_catalog.py` swaps a spec's `engine_factory` to build one of
these instead of the real engine when `DOCBOX_<ENGINE>_URL` is set for that engine.
"""

from __future__ import annotations

import io
import time

import requests
from PIL import Image

from docbox.backend.engines.base import ProgressCallback
from docbox.backend.schemas import OcrResult

_POLL_INTERVAL_S = 1.0
DEFAULT_RUN_TIMEOUT_S = 180.0


class EngineServiceError(RuntimeError):
    """A remote engine container was unreachable or rejected the request.

    Carries an HTTP status so routes can pass it through (503 when unreachable, the
    remote's own status otherwise) instead of collapsing everything into a bare 500 or
    misreporting an outage as "not downloaded".
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _remote_detail(resp: requests.Response) -> str:
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None
    return str(detail) if detail else f"engine service returned HTTP {resp.status_code}"


class RemoteEngine:
    """Proxies OCREngine calls for `model_id` to a sibling backend at `base_url`."""

    def __init__(
        self, *, base_url: str, model_id: str, run_timeout_s: float = DEFAULT_RUN_TIMEOUT_S
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._run_timeout_s = run_timeout_s

    def _request(self, method: str, path: str, *, timeout: float, **kwargs) -> requests.Response:
        try:
            resp = requests.request(method, f"{self._base_url}{path}", timeout=timeout, **kwargs)
        except requests.Timeout:
            raise EngineServiceError(
                504, f"Engine service at {self._base_url} timed out after {timeout:.0f}s"
            ) from None
        except requests.RequestException as exc:
            raise EngineServiceError(
                503, f"Engine service at {self._base_url} is unreachable: {exc}"
            ) from None
        if not resp.ok:
            raise EngineServiceError(resp.status_code, _remote_detail(resp))
        return resp

    def is_downloaded(self) -> bool:
        # Raises EngineServiceError when the container is down, rather than returning
        # False — an outage isn't the same as "not downloaded", and callers that just
        # need a best-effort answer (the model listing) catch it themselves.
        resp = self._request("GET", f"/api/models/{self._model_id}", timeout=5)
        return bool(resp.json().get("downloaded"))

    def download(self, progress_cb: ProgressCallback) -> None:
        resp = self._request("POST", f"/api/models/{self._model_id}/download", timeout=10)
        job_id = resp.json()["job_id"]

        while True:
            status = self._request(
                "GET",
                f"/api/models/{self._model_id}/download/status",
                params={"job_id": job_id},
                timeout=10,
            ).json()
            progress_cb(status.get("progress_pct") or 0.0, status.get("message") or "")
            if status["state"] == "done":
                return
            if status["state"] == "error":
                raise RuntimeError(status.get("message") or "remote download failed")
            time.sleep(_POLL_INTERVAL_S)

    def load(self) -> None:
        # The engine container loads its own model on each run; nothing to do here.
        pass

    def delete(self) -> None:
        self._request("DELETE", f"/api/models/{self._model_id}", timeout=30)

    def run(self, image: Image.Image) -> OcrResult:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        resp = self._request(
            "POST",
            "/api/ocr/run",
            data={"model_id": self._model_id},
            files={"file": ("image.png", buf.getvalue(), "image/png")},
            timeout=self._run_timeout_s,
        )
        return OcrResult.model_validate(resp.json())
