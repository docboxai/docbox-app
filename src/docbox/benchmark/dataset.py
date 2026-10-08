"""What a benchmark reads: the user's files and folders, or a manifest, each file with
optional reference ("ground truth") text.

Reference text for files and folders comes from sidecar files next to each document:
  invoice.gt.txt     the whole document (its pages joined by blank lines)
  invoice.p3.gt.txt  page 3 only
When a file has any page references, its pages are scored one by one against those (and
pages without one aren't scored); otherwise the whole document is scored against the
whole-document reference.

A manifest (`*.json`, or `*.jsonl` with one item per line) lists the files instead, paths
relative to the manifest:
  {"name": "Invoices", "items": [
    {"file": "a.pdf", "gt_file": "a.txt"},
    {"file": "b.png", "gt": "Total due $1,284.00"},
    {"file": "c.pdf", "pages": [{"page": 1, "gt": "..."}, {"page": 2, "gt_file": "c2.txt"}]}
  ]}

Sources are pluggable (DatasetSource): public benchmark sets can be added later as
another source without touching the runner.
"""

from __future__ import annotations

import glob
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from docbox.service.errors import Invalid, NotFound
from docbox.service.ocr import SUPPORTED_SUFFIXES, collect_files

_PAGE_SIDECAR = re.compile(r"^(?P<stem>.+)\.p(?P<page>\d+)\.gt\.txt$", re.IGNORECASE)


@dataclass
class BenchItem:
    path: Path
    # Unique within a run; how results, references and the UI refer to this file.
    id: str = ""
    # Reference for the whole document, and/or for single pages (1-based).
    reference: str | None = None
    page_references: dict[int, str] = field(default_factory=dict)

    @property
    def has_reference(self) -> bool:
        return self.reference is not None or bool(self.page_references)


@dataclass
class Dataset:
    items: list[BenchItem]
    name: str | None = None


class DatasetSource(Protocol):
    def load(self) -> Dataset: ...


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise Invalid(f"Can't read reference text {path}: {exc}") from None


def sidecar_references(doc: Path) -> tuple[str | None, dict[int, str]]:
    """The reference texts stored next to `doc`, if any."""
    whole_path = doc.with_name(f"{doc.stem}.gt.txt")
    whole = _read_text(whole_path) if whole_path.is_file() else None
    pages: dict[int, str] = {}
    for candidate in doc.parent.glob(f"{glob.escape(doc.stem)}.p*.gt.txt"):
        m = _PAGE_SIDECAR.match(candidate.name)
        if m and m["stem"] == doc.stem:
            pages[int(m["page"])] = _read_text(candidate)
    return whole, pages


@dataclass
class FilesSource:
    """Files and folders the user picked; references from sidecar files."""

    paths: list[Path]
    recursive: bool = False

    def load(self) -> Dataset:
        items = []
        for doc in collect_files(self.paths, recursive=self.recursive):
            if doc.suffix.lower() not in SUPPORTED_SUFFIXES:
                raise Invalid(f"Not an image or PDF: {doc}")
            whole, pages = sidecar_references(doc)
            items.append(BenchItem(path=doc, reference=whole, page_references=pages))
        roots = [Path(p).expanduser() for p in self.paths]
        _assign_ids(items, roots)
        name = roots[0].name if len(roots) == 1 and roots[0].is_dir() else None
        return Dataset(items=items, name=name)


@dataclass
class ManifestSource:
    path: Path

    def load(self) -> Dataset:
        base = self.path.parent
        try:
            raw = self.path.read_text(encoding="utf-8-sig")
            if self.path.suffix.lower() == ".jsonl":
                entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
                name = None
            else:
                data = json.loads(raw)
                entries = data["items"] if isinstance(data, dict) else data
                name = data.get("name") if isinstance(data, dict) else None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise Invalid(f"Can't read manifest {self.path}: {exc}") from None

        items = []
        for n, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict) or "file" not in entry:
                raise Invalid(f"{self.path}: item {n} has no \"file\"")
            doc = (base / entry["file"]).resolve()
            if not doc.is_file():
                raise NotFound(f"{self.path}: item {n}: no such file {doc}")
            items.append(BenchItem(
                path=doc,
                reference=self._text(entry, base),
                page_references={
                    int(p["page"]): text
                    for p in entry.get("pages", [])
                    if (text := self._text(p, base)) is not None
                },
            ))
        _assign_ids(items, [base])
        return Dataset(items=items, name=name or self.path.stem)

    @staticmethod
    def _text(entry: dict, base: Path) -> str | None:
        if "gt" in entry:
            return str(entry["gt"])
        if "gt_file" in entry:
            return _read_text(base / entry["gt_file"])
        return None


def _assign_ids(items: list[BenchItem], roots: Iterable[Path]) -> None:
    """Ids are paths relative to the folder the user gave (or the file name), made unique."""
    resolved_roots = [r.resolve() for r in roots if r.is_dir()]
    seen: set[str] = set()
    for item in items:
        doc = item.path.resolve()
        base = next((r for r in resolved_roots if doc.is_relative_to(r)), None)
        candidate = doc.relative_to(base).as_posix() if base else doc.name
        unique, n = candidate, 2
        while unique in seen:
            unique = f"{candidate} ({n})"
            n += 1
        seen.add(unique)
        item.id = unique


def is_manifest(path: Path) -> bool:
    return path.suffix.lower() in (".json", ".jsonl") and path.is_file()


def resolve(specs: Iterable[str | Path], *, recursive: bool = False) -> Dataset:
    """A dataset from what the user typed: manifests and/or files and folders."""
    specs = [Path(s).expanduser() for s in specs]
    if not specs:
        raise Invalid("Give at least one file, folder or manifest")
    manifests = [s for s in specs if is_manifest(s)]
    others = [s for s in specs if not is_manifest(s)]
    parts = [ManifestSource(m).load() for m in manifests]
    if others:
        parts.append(FilesSource(others, recursive=recursive).load())
    items = [item for part in parts for item in part.items]
    if not items:
        raise Invalid("No images or PDFs found")
    if len(parts) > 1:  # ids are only unique within one source
        _assign_ids(items, [s for s in specs if s.is_dir()] + [m.parent for m in manifests])
    name = parts[0].name if len(parts) == 1 else None
    return Dataset(items=items, name=name)
