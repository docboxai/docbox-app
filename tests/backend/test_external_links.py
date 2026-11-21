"""Every web page the desktop app opens goes through `desktop/src/links.rs::open`, which
opens only https pages. These check the addresses it can be handed: its own constants and
the ones the backend lists (prerequisite download pages, benchmark score sources, models'
published figures)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from docbox.backend.core.prerequisites import PREREQUISITES

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop" / "src"
LINKS = DESKTOP / "links.rs"
OCRBENCH = ROOT / "src" / "docbox" / "benchmark" / "ocrbench.json"


def _is_web_page(url: str) -> bool:
    p = urlsplit(url)
    return p.scheme == "https" and bool(p.netloc)


def _urls_in(value) -> list[str]:
    if isinstance(value, dict):
        return [u for v in value.values() for u in _urls_in(v)]
    if isinstance(value, list):
        return [u for v in value for u in _urls_in(v)]
    return [value] if isinstance(value, str) and value.startswith(("http://", "https://")) else []


def test_the_apps_own_links_are_https_constants() -> None:
    urls = re.findall(r'pub const [A-Z_]+: &str = "([^"]+)";', LINKS.read_text("utf-8"))
    assert urls, "the app's web pages are constants in desktop/src/links.rs"
    assert all(_is_web_page(u) for u in urls), urls


def test_pages_open_only_through_links_open() -> None:
    # cx.open_url anywhere else would skip the https check.
    direct = [
        f.relative_to(DESKTOP)
        for f in DESKTOP.rglob("*.rs")
        if f != LINKS and "open_url(" in f.read_text(encoding="utf-8")
    ]
    assert direct == []


def test_prerequisite_download_pages_are_web_pages() -> None:
    pages = [p["download_url"] for p in PREREQUISITES.values() if p.get("download_url")]
    assert pages and all(_is_web_page(u) for u in pages), pages


def test_benchmark_score_sources_are_web_pages() -> None:
    urls = _urls_in(json.loads(OCRBENCH.read_text(encoding="utf-8")))
    assert urls and all(_is_web_page(u) for u in urls), urls


def test_model_figure_sources_are_web_pages() -> None:
    import docbox.backend.models_catalog  # noqa: F401 — importing it fills the registry
    from docbox.backend.core.registry import registry

    urls = [s.figures_source for s in registry.list() if s.figures_source]
    assert urls and all(_is_web_page(u) for u in urls), urls
