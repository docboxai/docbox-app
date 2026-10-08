"""Every web page the app opens must be on the opener capability's allow-list, written the
way the webview sends it. The opener plugin compares URLs as exact strings, so a link to
"https://build.nvidia.com" (which a browser sends as "https://build.nvidia.com/") was
silently refused."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from docbox.backend.core.prerequisites import PREREQUISITES

ROOT = Path(__file__).resolve().parents[2]
CAPABILITY = ROOT / "src-tauri" / "capabilities" / "default.json"
FRONTEND = ROOT / "frontend" / "src"
OCRBENCH = ROOT / "src" / "docbox" / "benchmark" / "ocrbench.json"


def _normalised(url: str) -> str:
    # What `new URL(url).href` gives for a plain https link: lower-case scheme and host,
    # and "/" for an empty path.
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, p.fragment))


def _allowed() -> set[str]:
    permissions = json.loads(CAPABILITY.read_text(encoding="utf-8"))["permissions"]
    (opener,) = [
        p for p in permissions
        if isinstance(p, dict) and p.get("identifier") == "opener:allow-open-url"
    ]
    return {entry["url"] for entry in opener["allow"]}


def _urls_in(value) -> list[str]:
    if isinstance(value, dict):
        return [u for v in value.values() for u in _urls_in(v)]
    if isinstance(value, list):
        return [u for v in value for u in _urls_in(v)]
    return [value] if isinstance(value, str) and value.startswith("https://") else []


def test_allowed_urls_are_written_the_way_the_webview_sends_them() -> None:
    for url in _allowed():
        assert url == _normalised(url), f"write {url!r} as {_normalised(url)!r}"


def test_the_apps_own_links_are_allowed() -> None:
    urls = re.findall(r'"(https://[^"]+)"', (FRONTEND / "lib" / "external.ts").read_text("utf-8"))
    assert urls, "the app's external URLs are constants in lib/external.ts"
    assert {_normalised(u) for u in urls} <= _allowed()


def test_components_link_through_the_constants() -> None:
    # A literal href would bypass the constants (and this check), so links use them.
    literal = [
        f.relative_to(FRONTEND)
        for f in FRONTEND.rglob("*.tsx")
        if re.search(r'href="https?://', f.read_text(encoding="utf-8"))
    ]
    assert literal == []


def test_prerequisite_download_pages_are_allowed() -> None:
    pages = {_normalised(p["download_url"]) for p in PREREQUISITES.values() if p.get("download_url")}
    assert pages and pages <= _allowed()


def test_benchmark_score_sources_are_allowed() -> None:
    urls = _urls_in(json.loads(OCRBENCH.read_text(encoding="utf-8")))
    assert urls and {_normalised(u) for u in urls} <= _allowed()
