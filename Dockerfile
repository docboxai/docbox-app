# Runs the DocBox backend (FastAPI + OCR engines) headless, without the Tauri desktop
# shell — the shell is a native GUI window (WebView2/webkit2gtk) and doesn't containerize.
# Point a client at this container's /api/* instead of a locally-spawned backend by
# setting the frontend's API base URL, or call the endpoints directly (see /docs).
FROM python:3.12-slim

# tesseract-ocr: the Tesseract engine's actual binary. DocBox's own code deliberately
# never auto-installs this on a user's host (see tesseract_engine.py) but a container is
# DocBox's own controlled environment, not a user's machine, so installing it here is
# fine and makes the Tesseract engine usable out of the box.
# libgl1/libglib2.0-0: required by opencv-python, a transitive paddleocr/paddlepaddle dep.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# Engine packages to bake in, e.g. "--extra paddle" or "--extra easyocr" (pyproject
# extras). Each engine container gets only its own engine's packages (see
# docker-compose.yml), so e.g. the paddleocr image carries no PyTorch. Baked in at build
# time rather than installed on demand, so a recreated container doesn't redo it.
ARG UV_EXTRAS=""

# Install deps first, separately from app code, so an app-only code change doesn't
# invalidate the (large — paddlepaddle etc.) dependency layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project $UV_EXTRAS

COPY src ./src
RUN uv sync --locked --no-dev $UV_EXTRAS

ENV PATH="/app/.venv/bin:$PATH"

# Downloaded models (core/paths.py). Mount a volume here so they survive a recreate.
ENV DOCBOX_DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 8756

CMD ["python", "-m", "docbox.backend.main", "--host", "0.0.0.0", "--port", "8756"]
