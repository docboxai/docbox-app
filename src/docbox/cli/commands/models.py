"""docbox models list | show | install | remove"""

from __future__ import annotations

from docbox.cli.output import Output, table
from docbox.cli.prompt import confirm
from docbox.service import models as service
from docbox.service.errors import Invalid


def register(sub, common) -> None:
    p = sub.add_parser("models", help="list, install and remove OCR models")
    msub = p.add_subparsers(dest="command", metavar="<command>", required=True)

    ls = msub.add_parser("list", parents=[common], help="every model and whether it's ready")
    ls.add_argument("--ready", action="store_true", help="only models that can read now")
    ls.add_argument("--fits", action="store_true", help="only models that fit this computer")
    ls.set_defaults(func=_list)

    show = msub.add_parser("show", parents=[common], help="one model in detail")
    show.add_argument("model_id")
    show.set_defaults(func=_show)

    inst = msub.add_parser(
        "install", parents=[common],
        help="install a model (and its engine's packages the first time)",
    )
    inst.add_argument("model_id")
    inst.set_defaults(func=_install)

    rm = msub.add_parser("remove", parents=[common], help="delete a model's files")
    rm.add_argument("model_id")
    rm.add_argument("--yes", "-y", action="store_true", help="don't ask first")
    rm.set_defaults(func=_remove)


_STATUS = {
    "ready": "ready",
    "needs_download": "not installed",
    "needs_engine": "engine not installed",
    "needs_prerequisite": "needs a program",
}


def _list(args, out: Output) -> int:
    models = service.list_models()
    if args.ready:
        models = [m for m in models if m.status == "ready"]
    if args.fits:
        models = [m for m in models if m.fit.fits]

    def human() -> None:
        table(
            ["ID", "NAME", "STATUS", "SIZE", "FIT"],
            [
                [
                    m.id + (" *" if m.recommended else ""),
                    m.name,
                    _STATUS[m.status],
                    f"{m.approx_download_mb} MB" if m.approx_download_mb else "-",
                    m.fit.summary,
                ]
                for m in models
            ],
        )
        if any(m.recommended for m in models):
            print("\n* recommended for this computer")

    out.result(models, human)
    return 0


def _show(args, out: Output) -> int:
    m = service.get_model(args.model_id)

    def human() -> None:
        print(f"{m.name}  ({m.id})")
        print(m.description)
        print(f"Engine     {m.engine}")
        print(f"Status     {_STATUS[m.status]}")
        print(f"Languages  {', '.join(m.languages)}")
        print(f"Download   ~{m.approx_download_mb} MB · needs ~{m.approx_ram_mb} MB RAM")
        print(f"Fit        {m.fit.summary}")
        for reason in [*m.fit.reasons, *m.fit.notes]:
            print(f"           {reason}")
        if m.prerequisite:
            print(f"Needs      {m.prerequisite} (install it yourself; see `docbox` README)")

    out.result(m, human)
    return 0


def _install(args, out: Output) -> int:
    def progress(state: str, pct: float, message: str) -> None:
        out.progress(f"{state:<12} {pct:5.1f}%  {message}")

    service.install_model(args.model_id, progress)
    out.end_progress()
    model = service.get_model(args.model_id)
    out.result(model, lambda: print(f"Installed {model.name}. Status: {_STATUS[model.status]}"))
    return 0


def _remove(args, out: Output) -> int:
    model = service.get_model(args.model_id)
    if not confirm(f"Remove {model.name}'s files?", yes=args.yes):
        raise Invalid("Not removed.")
    service.remove_model(args.model_id)
    out.result({"removed": args.model_id}, lambda: print(f"Removed {model.name}."))
    return 0
