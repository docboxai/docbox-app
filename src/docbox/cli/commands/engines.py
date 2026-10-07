"""docbox engines list | remove"""

from __future__ import annotations

from docbox.cli.output import Output, human_bytes, table
from docbox.cli.prompt import confirm
from docbox.service import engines as service
from docbox.service.errors import Invalid


def register(sub, common) -> None:
    p = sub.add_parser("engines", help="engine packages on disk")
    esub = p.add_subparsers(dest="command", metavar="<command>", required=True)

    ls = esub.add_parser("list", parents=[common], help="each engine and the space it uses")
    ls.set_defaults(func=_list)

    rm = esub.add_parser(
        "remove", parents=[common], help="uninstall an engine and every model it downloaded",
    )
    rm.add_argument("engine", help="engine id, e.g. paddle or easyocr")
    rm.add_argument("--yes", "-y", action="store_true", help="don't ask first")
    rm.set_defaults(func=_remove)


def _list(args, out: Output) -> int:
    info = service.storage()

    def human() -> None:
        table(
            ["ENGINE", "NAME", "INSTALLED", "PACKAGES", "MODELS"],
            [
                [
                    e.id, e.name,
                    "removal pending" if e.removal_pending else ("yes" if e.installed else "no"),
                    human_bytes(e.package_bytes),
                    f"{e.models_downloaded} · {human_bytes(e.model_bytes)}",
                ]
                for e in info.engines
            ],
        )
        print(f"\nModels folder: {human_bytes(info.models_bytes)} in {info.data_dir}")

    out.result(info, human)
    return 0


def _remove(args, out: Output) -> int:
    if not confirm(f"Uninstall {args.engine} and all of its models?", yes=args.yes):
        raise Invalid("Not removed.")
    result = service.remove_engine(args.engine)
    out.result(result, lambda: print(result.detail))
    return 0
