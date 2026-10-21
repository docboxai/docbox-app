"""Registers the concrete OCR models DocBox knows about. Import for side effects.

Model ids/descriptions/sizes below deliberately span several axes of "variation" so the
hardware-fit check has something real to differentiate on:

- **Engine "nature"**: PaddleOCR's own det+rec deep-learning pipelines (multiple size
  tiers), PaddleOCR-VL's much heavier layout+vision-language-model pipeline, EasyOCR's
  alternate deep-learning pipeline (PyTorch-based), and Tesseract's classical
  engine+LSTM hybrid with a system-binary prerequisite.
- **Size/accuracy tier**: "mobile" (small, fast, lower accuracy) vs "server"/"medium"/VLM
  (larger, slower, higher accuracy) within the PaddleOCR family.
- **Language coverage**: English, Chinese, and language-family recognizers (Latin,
  Cyrillic, Arabic, Devanagari, Korean) verified against paddlex's official model
  catalog (`paddlex/inference/utils/official_models.py::ALL_MODELS`) rather than guessed.

Figures, and where they come from:

- Download sizes of the PP-OCR models are the det + rec model sizes PaddleOCR publishes
  (`_PADDLE_FIGURES`). The CPU/GPU speedup is its published detection time on an Intel
  Xeon Gold 6271C (8 threads) against a Tesla T4, where it publishes both.
- `approx_ram_mb` is the most memory a read takes, which is what decides whether a
  computer runs out. Nobody publishes it, so the PP-OCR figures are measured
  (`ram_measured=True`): the cgroup's peak memory reading a 1920x2000 page (the largest
  strip PaddleOcrEngine reads at once) with paddlepaddle 3.2.2 and oneDNN, on an Intel
  i5-12400F (6 cores), along with `cpu_page_seconds`. Every model peaked higher on a
  tall 1920x13768 screenshot read in 8 strips (paddle keeps some of each strip's memory):
  Mobile 1.35 GB against 1.0, Balanced up to 3.06 against 1.8, Large 3.19 against 2.7, so the
  figures are those. Mobile Chinese and the language
  families share a measured model's text finder, which takes nearly all of the memory, and
  are counted as it measured (their readers are 8-14 MB).
  The rest (PaddleOCR-VL, EasyOCR, Tesseract) are still estimates.
- `preferred_device`: "gpu" for the models a graphics card makes several times faster,
  "cpu" for ones that read a page in about a second on a processor anyway (Mobile, whose
  text finder takes ~57 ms on a CPU) or can't use one (Tesseract).
"""

from __future__ import annotations

import os
from dataclasses import replace

from docbox.backend.core.registry import ModelSpec, Tier, registry
from docbox.backend.engines.easyocr_engine import EasyOcrEngine
from docbox.backend.engines.paddleocr_engine import PaddleOcrEngine
from docbox.backend.engines.paddleocr_vl_engine import PaddleOcrVlEngine
from docbox.backend.engines.remote_engine import DEFAULT_RUN_TIMEOUT_S, RemoteEngine
from docbox.backend.engines.tesseract_engine import TesseractEngine

# `quality` ranks the built-in models for everyday documents; the recommendation is the
# best one that runs smoothly on this computer (registry.recommend). PaddleOCR's own
# tables (docs/version3.x/module_usage/text_detection.en.md and text_recognition.en.md)
# put PP-OCRv6 medium above PP-OCRv5 server on both detection (Hmean 86.2 vs 83.8) and
# recognition (+5.1%), at roughly a tenth of the CPU time for detection, so "Balanced"
# outranks "Large". Models for one language family keep quality=None.

_PADDLE_FIGURES = (
    "https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/module_usage/"
    "text_detection.en.md"
)
# PP-OCRv5_server_det: 383.15 ms on the CPU, 89.55 ms on the GPU.
_SERVER_DET_GPU_SPEEDUP = 4.3

# --- PaddleOCR: mobile tier (small, fast, CPU-friendly) ---------------------------

registry.register(
    ModelSpec(
        id="paddleocr-mobile-en",
        tier=Tier.LIGHT,
        quality=30,
        name="PaddleOCR Mobile — English",
        family="PaddleOCR — English",
        variant="Mobile",
        engine="paddleocr",
        requires_extra="paddle",
        description=(
            "Small and fast. Reads English text from scans, receipts and screenshots, "
            "and runs well on any computer."
        ),
        languages=["en"],
        approx_download_mb=12,
        approx_ram_mb=1400,
        min_disk_mb=200,
        cpu_page_seconds=1.3,
        ram_measured=True,
        figures_source=_PADDLE_FIGURES,
        engine_factory=lambda: PaddleOcrEngine(
            model_id="paddleocr-mobile-en",
            det_model_name="PP-OCRv4_mobile_det",
            rec_model_name="en_PP-OCRv4_mobile_rec",
        ),
    )
)

registry.register(
    ModelSpec(
        id="paddleocr-mobile-ch",
        tier=Tier.LIGHT,
        quality=20,
        name="PaddleOCR Mobile — Chinese + English",
        family="PaddleOCR — Chinese + English",
        variant="Mobile",
        engine="paddleocr",
        requires_extra="paddle",
        description=(
            "Small and fast, for documents that mix Chinese and English. Same size as "
            "the English-only version."
        ),
        languages=["ch", "en"],
        approx_download_mb=15,
        approx_ram_mb=1400,
        min_disk_mb=200,
        ram_measured=True,
        figures_source=_PADDLE_FIGURES,
        engine_factory=lambda: PaddleOcrEngine(
            model_id="paddleocr-mobile-ch",
            det_model_name="PP-OCRv4_mobile_det",
            rec_model_name="PP-OCRv4_mobile_rec",
        ),
    )
)

# --- PaddleOCR: balanced / large tiers --------------------------------------------

registry.register(
    ModelSpec(
        id="paddleocr-balanced",
        tier=Tier.STANDARD,
        quality=60,
        name="PaddleOCR Balanced — Chinese + English",
        family="PaddleOCR — Chinese + English",
        variant="Balanced",
        engine="paddleocr",
        requires_extra="paddle",
        description=(
            "The most accurate everyday reader, for English and Chinese text, at a "
            "moderate size and still quick."
        ),
        languages=["ch", "en"],
        approx_download_mb=133,
        approx_ram_mb=3100,
        min_disk_mb=300,
        cpu_page_seconds=4.7,
        preferred_device="gpu",
        ram_measured=True,
        figures_source=_PADDLE_FIGURES,
        engine_factory=lambda: PaddleOcrEngine(
            model_id="paddleocr-balanced",
            det_model_name="PP-OCRv6_medium_det",
            rec_model_name="PP-OCRv6_medium_rec",
        ),
    )
)

registry.register(
    ModelSpec(
        id="paddleocr-accurate-en",
        tier=Tier.STANDARD,
        quality=50,
        name="PaddleOCR Large — English",
        family="PaddleOCR — English",
        variant="Large",
        engine="paddleocr",
        requires_extra="paddle",
        description=(
            "The previous generation's larger version, with an English-only reader. "
            "Bigger and slower than Balanced, which usually reads better; worth a try "
            "when Balanced misses English text."
        ),
        languages=["en"],
        approx_download_mb=92,
        approx_ram_mb=3200,
        min_disk_mb=400,
        cpu_page_seconds=5.1,
        preferred_device="gpu",
        gpu_speedup=_SERVER_DET_GPU_SPEEDUP,
        ram_measured=True,
        figures_source=_PADDLE_FIGURES,
        engine_factory=lambda: PaddleOcrEngine(
            model_id="paddleocr-accurate-en",
            det_model_name="PP-OCRv5_server_det",
            rec_model_name="en_PP-OCRv5_mobile_rec",
        ),
    )
)

# --- PaddleOCR: language-family recognizers (PP-OCRv5 server det + family rec) ----

# (id, label, reader, languages, download MB: the 84 MB text finder plus the reader)
_LANGUAGE_FAMILIES = [
    ("paddleocr-latin", "Latin-script European", "latin_PP-OCRv5_mobile_rec",
     ["fr", "de", "es", "it", "pt", "nl"], 98),
    ("paddleocr-cyrillic", "Cyrillic", "cyrillic_PP-OCRv5_mobile_rec", ["ru", "uk", "bg"], 92),
    ("paddleocr-arabic", "Arabic", "arabic_PP-OCRv5_mobile_rec", ["ar"], 92),
    ("paddleocr-devanagari", "Devanagari", "devanagari_PP-OCRv5_mobile_rec", ["hi", "mr"], 92),
    ("paddleocr-korean", "Korean", "korean_PP-OCRv5_mobile_rec", ["ko"], 98),
]

for _model_id, _family_label, _rec_name, _langs, _download_mb in _LANGUAGE_FAMILIES:
    registry.register(
        ModelSpec(
            id=_model_id,
            tier=Tier.STANDARD,
            name=f"PaddleOCR — {_family_label}",
            engine="paddleocr",
            requires_extra="paddle",
            description=(
                f"Reads {_family_label} languages, using the same larger text finder "
                "as the Large English version."
            ),
            languages=_langs,
            approx_download_mb=_download_mb,
            approx_ram_mb=3200,
            min_disk_mb=400,
            ram_measured=True,
            preferred_device="gpu",
            gpu_speedup=_SERVER_DET_GPU_SPEEDUP,
            figures_source=_PADDLE_FIGURES,
            engine_factory=lambda det="PP-OCRv5_server_det", rec=_rec_name, mid=_model_id: (
                PaddleOcrEngine(model_id=mid, det_model_name=det, rec_model_name=rec)
            ),
        )
    )

# --- PaddleOCR-VL: heavy layout + vision-language-model document parser -----------

registry.register(
    ModelSpec(
        id="paddleocr-vl",
        tier=Tier.HEAVY,
        quality=90,
        name="PaddleOCR-VL — whole pages",
        engine="paddleocr-vl",
        requires_extra="paddle",
        description=(
            "Understands whole pages: headings, paragraphs and tables, in reading order. "
            "Much bigger and slower than the other versions; it needs a powerful "
            "computer, so most laptops will show it as a poor fit."
        ),
        languages=["ch", "en"],
        approx_download_mb=2000,
        approx_ram_mb=6000,
        min_disk_mb=4000,
        preferred_device="gpu",
        engine_factory=lambda: PaddleOcrVlEngine(model_id="paddleocr-vl"),
        slow_on_cpu=True,
    )
)

# --- Tesseract: classical engine, system-binary prerequisite ----------------------

for _tess_id, _tess_lang, _tess_label, _tess_quality in [
    ("tesseract-eng", "eng", "English", 10),
    ("tesseract-fra", "fra", "French", None),
]:
    registry.register(
        ModelSpec(
            id=_tess_id,
            quality=_tess_quality,
            name=f"Tesseract — {_tess_label}",
            engine="tesseract",
            prerequisite="tesseract",
            description=(
                "The classic Tesseract reader. Works best on clean, printed pages. Needs "
                "the Tesseract program on this computer; DocBox can install it for you on "
                "Windows."
            ),
            languages=[_tess_lang],
            approx_download_mb=4,
            approx_ram_mb=250,
            min_disk_mb=50,
            engine_factory=lambda lang=_tess_lang, mid=_tess_id: TesseractEngine(
                model_id=mid, lang=lang
            ),
        )
    )

# --- EasyOCR: alternate deep-learning pipeline, PyTorch-based ---------------------

registry.register(
    ModelSpec(
        id="easyocr-en",
        tier=Tier.STANDARD,
        quality=40,
        name="EasyOCR — English",
        engine="easyocr",
        requires_extra="easyocr",
        description=(
            "An alternative reader that often copes better with unusual fonts. The "
            "first time, DocBox also installs its engine, a larger one-time download."
        ),
        languages=["en"],
        approx_download_mb=100,
        approx_ram_mb=1500,
        min_disk_mb=2500,
        preferred_device="gpu",
        engine_factory=lambda: EasyOcrEngine(model_id="easyocr-en", langs=["en"]),
    )
)

# --- Optional: delegate whole engine families to their own containers -------------
#
# Splitting engines into separate containers (docker-compose.yml) is done here, once,
# rather than at each registration site above: when DOCBOX_<ENGINE>_URL is set for a
# given engine, every already-registered spec for that engine gets its
# `engine_factory` swapped to a RemoteEngine pointed at that container instead of the
# real in-process engine. Unset (the desktop dev-mode default) means every engine still
# runs in-process here, unchanged.
_REMOTE_ENGINE_URLS = {
    engine: url
    for engine, url in (
        ("paddleocr", os.environ.get("DOCBOX_PADDLEOCR_URL")),
        ("paddleocr-vl", os.environ.get("DOCBOX_PADDLEOCR_VL_URL")),
        ("tesseract", os.environ.get("DOCBOX_TESSERACT_URL")),
        ("easyocr", os.environ.get("DOCBOX_EASYOCR_URL")),
    )
    if url
}

# The engine container rebuilds its pipeline on every run, and PaddleOCR-VL's
# vision-language model alone can take minutes to load on CPU before inference starts.
_REMOTE_RUN_TIMEOUT_S = {"paddleocr-vl": 900.0}

if _REMOTE_ENGINE_URLS:
    for _spec in list(registry.list()):
        _url = _REMOTE_ENGINE_URLS.get(_spec.engine)
        if _url is None:
            continue
        _timeout = _REMOTE_RUN_TIMEOUT_S.get(_spec.engine, DEFAULT_RUN_TIMEOUT_S)
        registry.register(
            replace(
                _spec,
                engine_factory=lambda u=_url, mid=_spec.id, t=_timeout: RemoteEngine(
                    base_url=u, model_id=mid, run_timeout_s=t
                ),
                # The engine container has its own packages/binaries baked in; this
                # orchestrator never installs or checks them itself.
                requires_extra=None,
                prerequisite=None,
            )
        )
