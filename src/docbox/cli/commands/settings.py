"""docbox settings show | set"""

from __future__ import annotations

from docbox.backend.schemas import SettingsUpdate
from docbox.cli.output import Output
from docbox.service import settings as service
from docbox.service.errors import Invalid


def register(sub, common) -> None:
    p = sub.add_parser("settings", help="default model and the cloud-engine switch")
    ssub = p.add_subparsers(dest="command", metavar="<command>", required=True)

    show = ssub.add_parser("show", parents=[common], help="current settings")
    show.set_defaults(func=_show)

    st = ssub.add_parser("set", parents=[common], help="change a setting")
    st.add_argument("key", choices=["default-model", "cloud"])
    st.add_argument("value", help="a model id or 'none' / 'on' or 'off'")
    st.set_defaults(func=_set)


def _print(s) -> None:
    print(f"Default model  {s.default_model_id or '(none)'}")
    print(f"Cloud engine   {'on' if s.cloud_enabled else 'off'}")
    print(f"Output folder  {s.output_dir}")


def _show(args, out: Output) -> int:
    s = service.get_settings()
    out.result(s, lambda: _print(s))
    return 0


def _set(args, out: Output) -> int:
    if args.key == "default-model":
        update = SettingsUpdate(default_model_id="" if args.value == "none" else args.value)
    else:
        if args.value not in ("on", "off"):
            raise Invalid("cloud takes 'on' or 'off'")
        update = SettingsUpdate(cloud_enabled=args.value == "on")
    s = service.update_settings(update)
    out.result(s, lambda: _print(s))
    return 0
