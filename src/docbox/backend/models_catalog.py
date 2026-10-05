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

Download/RAM/disk figures are estimates for hardware-fit purposes, not measured exactly
for every entry — PaddleOCR mobile-tier figures were confirmed against a real download in
this environment; the heavier entries (PaddleOCR-VL, EasyOCR, "server"-tier PaddleOCR)
are reasoned estimates based on their known model class/parameter scale.
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
# outranks "High Accuracy". Models for one language family keep quality=None.

# --- PaddleOCR: mobile tier (small, fast, CPU-friendly) ---------------------------

registry.register(
    ModelSpec(
        id="paddleocr-mobile-en",
        tier=Tier.LIGHT,
        quality=30,
        name="PaddleOCR Mobile — English",
        engine="paddleocr",
        requires_extra="paddle",
        description=(
            "Small and fast. Reads English text from scans, receipts and screenshots, "
            "and runs well on any computer."
        ),
        languages=["en"],
        approx_download_mb=20,
        approx_ram_mb=800,
        min_disk_mb=200,
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
        engine="paddleocr",
        requires_extra="paddle",
        description=(
            "Small and fast, for documents that mix Chinese and English. Same size as "
            "the English-only version."
        ),
        languages=["ch", "en"],
        approx_download_mb=20,
        approx_ram_mb=800,
        min_disk_mb=200,
        engine_factory=lambda: PaddleOcrEngine(
            model_id="paddleocr-mobile-ch",
            det_model_name="PP-OCRv4_mobile_det",
            rec_model_name="PP-OCRv4_mobile_rec",
        ),
    )
)

# --- PaddleOCR: balanced / high-accuracy tiers -------------------------------------

registry.register(
    ModelSpec(
        id="paddleocr-balanced",
        tier=Tier.STANDARD,
        quality=60,
        name="PaddleOCR Balanced — Chinese + English",
        engine="paddleocr",
        requires_extra="paddle",
        description=(
            "The most accurate everyday reader, for English and Chinese text, at a "
            "moderate size and still quick."
        ),
        languages=["ch", "en"],
        approx_download_mb=90,
        approx_ram_mb=1200,
        min_disk_mb=300,
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
        name="PaddleOCR High Accuracy — English",
        engine="paddleocr",
        requires_extra="paddle",
        description=(
            "Careful at finding small or crowded English text, like fine print and busy "
            "forms. Larger and slower than Balanced."
        ),
        languages=["en"],
        approx_download_mb=170,
        approx_ram_mb=1500,
        min_disk_mb=400,
        engine_factory=lambda: PaddleOcrEngine(
            model_id="paddleocr-accurate-en",
            det_model_name="PP-OCRv5_server_det",
            rec_model_name="en_PP-OCRv5_mobile_rec",
        ),
    )
)

# --- PaddleOCR: language-family recognizers (PP-OCRv5 server det + family rec) ----

_LANGUAGE_FAMILIES = [
    ("paddleocr-latin", "Latin-script European", "latin_PP-OCRv5_mobile_rec",
     ["fr", "de", "es", "it", "pt", "nl"]),
    ("paddleocr-cyrillic", "Cyrillic", "cyrillic_PP-OCRv5_mobile_rec", ["ru", "uk", "bg"]),
    ("paddleocr-arabic", "Arabic", "arabic_PP-OCRv5_mobile_rec", ["ar"]),
    ("paddleocr-devanagari", "Devanagari", "devanagari_PP-OCRv5_mobile_rec", ["hi", "mr"]),
    ("paddleocr-korean", "Korean", "korean_PP-OCRv5_mobile_rec", ["ko"]),
]

for _model_id, _family_label, _rec_name, _langs in _LANGUAGE_FAMILIES:
    registry.register(
        ModelSpec(
            id=_model_id,
            tier=Tier.STANDARD,
            name=f"PaddleOCR — {_family_label}",
            engine="paddleocr",
            requires_extra="paddle",
            description=(
                f"Reads {_family_label} languages with the same careful text-finding "
                "as the high-accuracy English version."
            ),
            languages=_langs,
            approx_download_mb=170,
            approx_ram_mb=1500,
            min_disk_mb=400,
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
