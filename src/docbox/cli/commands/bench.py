"""docbox bench run | list | show | page | report | cancel | delete"""

from __future__ import annotations

import sys
import time

from docbox.benchmark.store import BenchRun
from docbox.cli.output import EXIT_ERROR, Output, table
from docbox.cli.prompt import confirm
from docbox.service import benchmarks as service
from docbox.service.errors import Invalid


def register(sub, common) -> None:
    p = sub.add_parser("bench", help="benchmark OCR models on your own documents")
    bsub = p.add_subparsers(dest="command", metavar="<command>", required=True)

    run = bsub.add_parser(
        "run", parents=[common],
        help="read files with several models and compare them",
        description="Each model reads every page in its own process, one model after "
        "another. Reference text is optional: put invoice.gt.txt (whole document) or "
        "invoice.p2.gt.txt (one page) next to invoice.pdf, or pass a manifest .json/.jsonl.",
    )
    run.add_argument("sources", nargs="+", help="files, folders or manifests")
    run.add_argument("--models", "-m",
                     help="comma-separated model ids (default: every model that's ready)")
    run.add_argument("--name", help="name for this run")
    run.add_argument("--recursive", "-r", action="store_true", help="include subfolders")
    run.add_argument("--install-missing", action="store_true",
                     help="install models that aren't installed yet instead of skipping them")
    run.add_argument("--ignore-case", action="store_true", help="score without case")
    run.add_argument("--page-timeout", type=float, default=300,
                     help="seconds to wait for one page before giving up on a model")
    run.set_defaults(func=_run)

    ls = bsub.add_parser("list", parents=[common], help="saved benchmark runs")
    ls.set_defaults(func=_list)

    show = bsub.add_parser("show", parents=[common], help="a run's leaderboard")
    show.add_argument("run_id")
    show.set_defaults(func=_show)

    page = bsub.add_parser("page", parents=[common],
                           help="every model's reading of one page, mistakes marked")
    page.add_argument("run_id")
    page.add_argument("file_id")
    page.add_argument("page", type=int, nargs="?", default=1)
    page.add_argument("--against", help="compare with this model's reading (no reference)")
    page.set_defaults(func=_page)

    rep = bsub.add_parser("report", parents=[common], help="print a run's report")
    rep.add_argument("run_id")
    rep.add_argument("--format", "-f", choices=["md", "json", "csv"], default="md")
    rep.set_defaults(func=_report)

    cancel = bsub.add_parser("cancel", parents=[common], help="stop a running benchmark")
    cancel.add_argument("run_id")
    cancel.set_defaults(func=_cancel)

    rm = bsub.add_parser("delete", parents=[common], help="delete a saved run")
    rm.add_argument("run_id")
    rm.add_argument("--yes", "-y", action="store_true", help="don't ask first")
    rm.set_defaults(func=_delete)


def _pct(v: float | None) -> str:
    return "–" if v is None else f"{v * 100:.1f}%"


def _num(v: float | None, fmt: str = "{:.2f}") -> str:
    return "–" if v is None else fmt.format(v)


def _print_run(run: BenchRun) -> None:
    print(f"{run.name}  ({run.id})  {run.state}")
    print(f"{len(run.files)} files · {run.pages_total} pages · {len(run.models)} models"
          + ("" if run.has_reference else " · no reference text, ranked by speed"))
    if run.summary:
        print()
        table(
            ["#", "MODEL", "ACCURACY", "WER", "S/PAGE", "LOAD S", "PEAK RAM", "CONF", "FAILED"],
            [
                [r.rank or "–", r.model_id, _pct(r.accuracy), _pct(r.wer),
                 _num(r.seconds_per_page), _num(r.load_seconds, "{:.1f}"),
                 _num(r.peak_memory_mb, "{:.0f} MB"), _pct(r.mean_confidence), r.pages_failed]
                for r in run.summary.leaderboard
            ],
        )
    for m in run.models:
        if m.error:
            print(f"\n{m.name}: {m.error.splitlines()[0]}")


def _run(args, out: Output) -> int:
    config = service.BenchConfig(
        sources=args.sources,
        models=[m.strip() for m in (args.models or "").split(",") if m.strip()],
        name=args.name, recursive=args.recursive, install_missing=args.install_missing,
        ignore_case=args.ignore_case, page_timeout=args.page_timeout, source="cli",
    )
    started = time.monotonic()

    def progress(run: BenchRun) -> None:
        total = max(1, run.pages_total * len(run.models))
        current = next((m for m in run.models if m.model_id == run.current_model_id), None)
        doing = f"{current.name}: {current.state}" if current else run.state
        out.progress(f"{run.pages_done}/{total} pages · {doing} · "
                     f"{time.monotonic() - started:.0f} s")

    try:
        run = service.run_now(config, progress)
    except KeyboardInterrupt:
        out.end_progress()
        print("Stopped; the pages read so far are saved.", file=sys.stderr)
        raise
    out.end_progress()

    def human() -> None:
        _print_run(run)
        print(f"\nReport: docbox bench report {run.id}")

    out.result(run, human)
    return 0 if run.state == "done" else EXIT_ERROR


def _list(args, out: Output) -> int:
    runs = service.list_runs()

    def human() -> None:
        table(
            ["ID", "NAME", "STATE", "FILES", "PAGES", "MODELS", "BEST"],
            [
                [r.id, r.name, r.state, len(r.files), r.pages_total, len(r.models),
                 r.summary.best_model_id if r.summary else ""]
                for r in runs
            ],
        )

    out.result([r.model_dump(exclude={"summary"}) | {
        "best_model_id": r.summary.best_model_id if r.summary else None} for r in runs], human)
    return 0


def _show(args, out: Output) -> int:
    run = service.get(args.run_id)
    out.result(run, lambda: _print_run(run))
    return 0


def _page(args, out: Output) -> int:
    view = service.page(args.run_id, args.file_id, args.page, args.against)

    def human() -> None:
        print(f"{view.file_id} · page {view.page} of {view.pages}")
        if view.reference is not None:
            label = "Reference" if view.reference_kind == "reference" \
                else f"Compared with {view.reference_model_id}"
            print(f"\n{label}:\n{view.reference.strip()}")
        for r in view.reads:
            slips = "" if r.slips is None else f" · {r.slips} slip{'s' * (r.slips != 1)}"
            print(f"\n{r.name}{slips}")
            print(r.error or r.text.strip())

    out.result(view, human)
    return 0


def _report(args, out: Output) -> int:
    text = service.render_report(args.run_id, args.format)
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def _cancel(args, out: Output) -> int:
    run = service.cancel(args.run_id)
    out.result({"cancelling": run.id}, lambda: print(f"Stopping {run.name}…"))
    return 0


def _delete(args, out: Output) -> int:
    if not confirm(f"Delete benchmark {args.run_id}?", yes=args.yes):
        raise Invalid("Not deleted.")
    service.delete(args.run_id)
    out.result({"deleted": args.run_id}, lambda: print("Deleted."))
    return 0
