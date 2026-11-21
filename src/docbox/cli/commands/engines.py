"""docbox engines list | remove | gpu | build"""

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

    g = esub.add_parser(
        "gpu", parents=[common],
        help="the graphics card, and which engines read on it",
    )
    g.set_defaults(func=_gpu)

    b = esub.add_parser(
        "build", parents=[common],
        help="install an engine's graphics-card (gpu) or processor (cpu) build",
    )
    b.add_argument("engine", help="paddle or easyocr")
    b.add_argument("build", choices=["gpu", "cpu"])
    b.add_argument("--yes", "-y", action="store_true", help="don't ask first")
    b.set_defaults(func=_build)


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


def _gpu(args, out: Output) -> int:
    status = service.gpu_status()

    def human() -> None:
        if status.name:
            free = f", {status.memory_free_gb:g} GB free" if status.memory_free_gb else ""
            print(f"Graphics   {status.name} ({status.memory_total_gb:g} GB{free})")
            print(f"Driver     {status.driver_version or '?'} · CUDA {status.cuda_version or '?'}"
                  f" (DocBox needs {status.cuda_required})")
        print(f"Usable     {'yes' if status.usable else 'no: ' + (status.reason or '')}")
        table(
            ["ENGINE", "NAME", "BUILD", "GPU DOWNLOAD", "NOTE"],
            [
                [e.id, e.name, e.installed or "not installed",
                 human_bytes(e.gpu_download_mb * 2**20),
                 "switch pending a restart" if e.pending_restart else (e.blocked or "")]
                for e in status.engines
            ],
        )

    out.result(status, human)
    return 0


def _build(args, out: Output) -> int:
    status = service.gpu_status()
    engine = next((e for e in status.engines if e.id == args.engine), None)
    if engine is not None and args.build == "gpu" and engine.installed != "gpu":
        size = human_bytes(engine.gpu_download_mb * 2**20)
        question = f"Download {engine.name} for the graphics card (about {size})?"
    else:
        question = f"Switch {args.engine} to its {args.build} build?"
    if not confirm(question, yes=args.yes):
        raise Invalid("Not changed.")
    detail = service.switch_build(
        args.engine, args.build,
        lambda pct, message: out.progress(f"installing   {pct:5.1f}%  {message}"),
    )
    out.end_progress()
    out.result({"engine": args.engine, "build": args.build, "detail": detail},
               lambda: print(detail))
    return 0


def _remove(args, out: Output) -> int:
    if not confirm(f"Uninstall {args.engine} and all of its models?", yes=args.yes):
        raise Invalid("Not removed.")
    result = service.remove_engine(args.engine)
    out.result(result, lambda: print(result.detail))
    return 0
