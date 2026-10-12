"""Tesseract reads with the language files DocBox downloaded into its own data folder."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from docbox.backend.engines.tesseract_engine import TesseractEngine, find_tesseract_binary


def _installed_eng_traineddata(binary: str) -> Path | None:
    """The eng.traineddata that came with the tesseract program, wherever it keeps it."""
    out = subprocess.run([binary, "--list-langs"], capture_output=True, text=True, timeout=30,
                         check=False)
    # 'List of available languages in "C:\Program Files\Tesseract-OCR/tessdata/" (3):'
    for line in (out.stdout + out.stderr).splitlines():
        if line.startswith("List of available languages in"):
            folder = Path(line.split('"')[1])
            candidate = folder / "eng.traineddata"
            return candidate if candidate.exists() else None
    return None


def test_reads_with_the_language_file_in_docbox_data_folder(tmp_path, monkeypatch) -> None:
    """On Windows the folder was passed as --tessdata-dir "<path>", and pytesseract kept the
    quotes: every read failed with "Error opening data file". The data folder here has a
    space in it too, as user folders on Windows often do."""
    binary = find_tesseract_binary()
    if binary is None:
        pytest.skip("the tesseract program isn't installed here")
    traineddata = _installed_eng_traineddata(binary)
    if traineddata is None:
        pytest.skip("tesseract has no English language file to copy")

    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)  # the engine sets it
    data_dir = tmp_path / "Data Folder"
    monkeypatch.setenv("DOCBOX_DATA_DIR", str(data_dir))
    tessdata = data_dir / "models" / "tesseract" / "tessdata"
    tessdata.mkdir(parents=True)
    shutil.copy(traineddata, tessdata / "eng.traineddata")

    image = Image.new("RGB", (900, 160), "white")
    ImageDraw.Draw(image).text((30, 40), "INVOICE 2048", fill="black",
                               font=ImageFont.load_default(size=64))

    engine = TesseractEngine(model_id="tesseract-eng", lang="eng")
    assert engine.is_downloaded()
    result = engine.run(image)
    assert "INVOICE" in " ".join(line.text for line in result.lines)
