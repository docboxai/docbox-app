"""Published OCRBench v1 / v2 scores for the vision-language models in DocBox's catalog,
shown next to the user's own benchmark results. The data is a hand-checked snapshot
(ocrbench.json, with a source for every score); OCRBench doesn't cover classic OCR
engines, so Tesseract, PaddleOCR and EasyOCR have no entry."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from pydantic import BaseModel


class V1Score(BaseModel):
    value: float
    self_reported: bool
    source: str
    url: str


class V2Score(BaseModel):
    en: float | None = None
    zh: float | None = None
    self_reported: bool
    source: str
    url: str


class ModelScores(BaseModel):
    ocrbench_v1: V1Score | None = None
    ocrbench_v2: V2Score | None = None


class ReferenceModel(BaseModel):
    model_id: str
    label: str
    scores: ModelScores


class BenchmarkInfo(BaseModel):
    name: str
    max: float
    about: str
    url: str
    splits: list[str] = []


class ReferenceData(BaseModel):
    benchmarks: dict[str, BenchmarkInfo]
    models: list[ReferenceModel]
    notes: list[str]
    checked: str


@cache
def reference() -> ReferenceData:
    path = Path(__file__).with_name("ocrbench.json")
    return ReferenceData.model_validate_json(path.read_text(encoding="utf-8"))
