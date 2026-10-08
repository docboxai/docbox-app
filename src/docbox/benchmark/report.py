"""Turning a run's page results into a leaderboard, a report, and a side-by-side view of
one page (every model's reading against the reference, mistakes marked)."""

from __future__ import annotations

import csv
import io
import statistics
import time
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel
from rapidfuzz.distance import Levenshtein

import docbox.backend.models_catalog  # noqa: F401 — importing it fills the registry
from docbox.backend import platforms
from docbox.benchmark import metrics
from docbox.benchmark.store import (
    BenchRun,
    BenchSummary,
    LeaderboardRow,
    PageResult,
    References,
)
from docbox.service.errors import Invalid, NotFound


def _model_scores(
    by_page: dict[tuple[str, int], PageResult], run: BenchRun, refs: References,
    *, reading: bool = False,
) -> list[metrics.Score]:
    """Edits against every reference in the run, one score per reference (a page, or a
    whole document): added up they give the model's error rates, and their spread gives
    the interval around them. A page the model failed counts as read empty, so failing
    doesn't score better than reading badly. Page references are used for files that
    have them; otherwise the whole-document reference. While the model is still
    `reading`, only references for pages it has got to count, so the live leaderboard
    doesn't score its unread pages as blank."""
    units: list[metrics.Score] = []
    for file in run.files:
        def text(page: int, file_id: str = file.id) -> str:
            r = by_page.get((file_id, page))
            return r.text if r is not None and r.error is None else ""

        def reached(page: int, file_id: str = file.id) -> bool:
            return not reading or (file_id, page) in by_page

        if file.id in refs.pages:
            for page, ref in refs.pages[file.id].items():
                if reached(int(page)):
                    units.append(metrics.score(text(int(page)), ref, ignore_case=run.ignore_case))
        elif file.id in refs.whole and all(reached(p) for p in range(1, file.pages + 1)):
            hyp = "\n\n".join(text(p) for p in range(1, file.pages + 1))
            units.append(metrics.score(hyp, refs.whole[file.id], ignore_case=run.ignore_case))
    return units


def summarize(run: BenchRun, results: list[PageResult], refs: References) -> BenchSummary:
    per_model: dict[str, dict[tuple[str, int], PageResult]] = defaultdict(dict)
    for r in results:
        per_model[r.model_id][(r.file_id, r.page)] = r
    scored = bool(refs.pages or refs.whole)

    rows = []
    for model in run.models:
        pages = per_model.get(model.model_id, {})
        ok = [r for r in pages.values() if r.error is None]
        seconds = [r.seconds for r in ok if r.seconds is not None]
        confidences = [ln.confidence for r in ok for ln in r.lines if ln.confidence is not None]
        engine, family, variant = platforms.describe(model.model_id)
        row = LeaderboardRow(
            model_id=model.model_id,
            name=model.name,
            engine=engine,
            family=family,
            variant=variant,
            pages_read=len(ok),
            pages_failed=len(pages) - len(ok),
            load_seconds=model.load_seconds,
            seconds_per_page=round(statistics.fmean(seconds), 3) if seconds else None,
            median_seconds_per_page=round(statistics.median(seconds), 3) if seconds else None,
            peak_memory_mb=model.peak_memory_mb,
            memory_note=model.memory_note,
            mean_confidence=round(statistics.fmean(confidences), 4) if confidences else None,
        )
        if scored and ok:
            units = _model_scores(pages, run, refs, reading=model.state == "running")
            s = sum(units, metrics.ZERO)
            if s.ref_chars:
                row.cer, row.wer = round(s.cer, 4), round(s.wer, 4)
                row.accuracy = round(max(0.0, 1 - s.cer), 4)
                margin = metrics.cer_margin(units)
                row.accuracy_margin = None if margin is None else round(margin, 4)
                row.scored_units = len(units)
                row.scored_chars = s.ref_chars
        rows.append(row)

    def key(row: LeaderboardRow):
        speed = row.seconds_per_page if row.seconds_per_page is not None else float("inf")
        # A model with nothing scored yet (still reading towards its first reference)
        # goes after the scored ones.
        cer = row.cer if row.cer is not None else float("inf")
        return (cer, speed) if scored else (speed,)

    ranked = sorted((r for r in rows if r.pages_read), key=key)
    for n, row in enumerate(ranked, start=1):
        row.rank = n
    unranked = [r for r in rows if not r.pages_read]
    return BenchSummary(
        ranked_by="cer" if scored else "speed",
        leaderboard=ranked + unranked,
        best_model_id=ranked[0].model_id if ranked else None,
    )


# --- output formats ---------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None, fmt: str = "{:.2f}", unit: str = "") -> str:
    return "–" if value is None else fmt.format(value) + unit


def _accuracy(row: LeaderboardRow) -> str:
    if row.accuracy is None or row.accuracy_margin is None:
        return _pct(row.accuracy)
    return f"{_pct(row.accuracy)} ±{row.accuracy_margin * 100:.1f}"


def to_markdown(run: BenchRun) -> str:
    summary = run.summary
    started = time.strftime("%Y-%m-%d %H:%M", time.localtime(run.created_at))
    lines = [
        f"# {run.name}",
        "",
        f"DocBox benchmark `{run.id}` · {started} · {run.state}",
        "",
        f"{len(run.files)} file{'s' * (len(run.files) != 1)}, {run.pages_total} "
        f"page{'s' * (run.pages_total != 1)}, {len(run.models)} "
        f"model{'s' * (len(run.models) != 1)}. "
        + ("Ranked by character error rate against the reference text."
           if summary and summary.ranked_by == "cer"
           else "No reference text, so ranked by speed."),
        "",
    ]
    if summary:
        lines += [
            ("| # | Model | Accuracy | CER | WER | s / page | Load s | Peak RAM | Confidence "
             "| Pages failed |"),
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in summary.leaderboard:
            lines.append(
                f"| {r.rank or '–'} | {r.name} (`{r.model_id}`) | {_accuracy(r)} "
                f"| {_pct(r.cer)} | {_pct(r.wer)} | {_num(r.seconds_per_page)} "
                f"| {_num(r.load_seconds, '{:.1f}')} | {_num(r.peak_memory_mb, '{:.0f}', ' MB')} "
                f"| {_pct(r.mean_confidence)} | {r.pages_failed} |"
            )
        if any(r.accuracy_margin is not None for r in summary.leaderboard):
            lines += ["", ("± is a 95% interval: how much accuracy varies between the pages "
                           "or documents that have reference text.")]
    problems = [m for m in run.models if m.error]
    if problems:
        lines += ["", "## Problems", ""]
        lines += [f"- **{m.name}**: {m.error.splitlines()[0]}" for m in problems]
    lines += ["", "## Files", ""]
    lines += [
        f"- `{f.id}`: {f.pages} page{'s' * (f.pages != 1)}"
        + (", with reference text" if f.has_reference else "")
        for f in run.files
    ]
    return "\n".join(lines) + "\n"


def to_csv(run: BenchRun) -> str:
    buf = io.StringIO()
    fields = list(LeaderboardRow.model_fields)
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in run.summary.leaderboard if run.summary else []:
        writer.writerow(row.model_dump())
    return buf.getvalue()


# --- one page, every model --------------------------------------------------------------


class DiffSpan(BaseModel):
    # Relative to the reference: "equal" text, text the model "insert"ed, reference text
    # it "delete"d (missed), or reference text it "replace"d with `text`.
    op: Literal["equal", "insert", "delete", "replace"]
    text: str
    reference: str = ""


class PageRead(BaseModel):
    model_id: str
    name: str
    text: str
    error: str | None = None
    seconds: float | None = None
    mean_confidence: float | None = None
    # Mistakes against the reference: changed runs of characters, and the error rate.
    slips: int | None = None
    cer: float | None = None
    diff: list[DiffSpan] = []


class PageView(BaseModel):
    run_id: str
    file_id: str
    page: int
    pages: int
    # "reference": the given reference text; "model": another model's reading; "none".
    reference_kind: Literal["reference", "model", "none"]
    reference_model_id: str | None = None
    reference: str | None = None
    reads: list[PageRead]


def _layout(text: str) -> str:
    """Text for showing a diff: lines kept (they help reading), but each line normalised
    like the score is and blank lines dropped, so layout alone never counts as a slip."""
    lines = (metrics.normalize(line) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _diff(reference: str, text: str, *, ignore_case: bool = False) -> list[DiffSpan]:
    reference, text = _layout(reference), _layout(text)
    spans = []
    for op in Levenshtein.opcodes(reference, text):
        ref_part = reference[op.src_start:op.src_end]
        hyp_part = text[op.dest_start:op.dest_end]
        same = (ref_part.split() == hyp_part.split()) or (
            ignore_case and ref_part.casefold() == hyp_part.casefold())
        if op.tag == "equal" or same:
            # A line break where the reference has a space reads the same.
            spans.append(DiffSpan(op="equal", text=hyp_part))
        elif op.tag == "insert":
            spans.append(DiffSpan(op="insert", text=hyp_part))
        elif op.tag == "delete":
            spans.append(DiffSpan(op="delete", text="", reference=ref_part))
        else:
            spans.append(DiffSpan(op="replace", text=hyp_part, reference=ref_part))
    # Neighbouring edits are one slip ("1,2B4" for "1,284"), and equal runs join up.
    merged: list[DiffSpan] = []
    for span in spans:
        prev = merged[-1] if merged else None
        if prev and span.op == "equal" and prev.op == "equal":
            merged[-1] = DiffSpan(op="equal", text=prev.text + span.text)
        elif prev and span.op != "equal" and prev.op != "equal":
            merged[-1] = DiffSpan(op="replace", text=prev.text + span.text,
                                  reference=prev.reference + span.reference)
        else:
            merged.append(span)
    return merged


def page_view(
    run: BenchRun, results: list[PageResult], refs: References, file_id: str, page: int,
    against: str | None = None,
) -> PageView:
    """Every model's reading of one page. Compared against the page's reference text if
    there is one (a whole-document reference only for one-page files), else against the
    reading of model `against` when given."""
    file = next((f for f in run.files if f.id == file_id), None)
    if file is None:
        raise NotFound(f"No file {file_id!r} in this benchmark")
    if not 1 <= page <= file.pages:
        raise NotFound(f"{file_id} has pages 1 to {file.pages}")

    by_model = {r.model_id: r for r in results if r.file_id == file_id and r.page == page}
    reference: str | None = refs.pages.get(file_id, {}).get(str(page))
    if reference is None and file.pages == 1:
        reference = refs.whole.get(file_id)
    kind: Literal["reference", "model", "none"] = "reference" if reference is not None else "none"
    if reference is None and against:
        if against not in by_model:
            raise Invalid(f"{against} has no reading of this page")
        reference, kind = by_model[against].text, "model"

    reads = []
    for model in run.models:
        r = by_model.get(model.model_id)
        if r is None:
            continue
        confidences = [ln.confidence for ln in r.lines if ln.confidence is not None]
        read = PageRead(
            model_id=model.model_id, name=model.name, text=r.text, error=r.error,
            seconds=r.seconds,
            mean_confidence=round(statistics.fmean(confidences), 4) if confidences else None,
        )
        if reference is not None and r.error is None:
            read.diff = _diff(reference, r.text, ignore_case=run.ignore_case)
            read.slips = sum(1 for s in read.diff if s.op != "equal")
            read.cer = round(metrics.cer(r.text, reference, ignore_case=run.ignore_case), 4)
        reads.append(read)
    return PageView(
        run_id=run.id, file_id=file_id, page=page, pages=file.pages, reference_kind=kind,
        reference_model_id=against if kind == "model" else None, reference=reference,
        reads=reads,
    )
