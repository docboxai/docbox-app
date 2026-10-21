"""docbox device"""

from __future__ import annotations

from docbox.backend.core import gpu
from docbox.cli.output import Output
from docbox.service.device import device_info


def register(sub, common) -> None:
    p = sub.add_parser(
        "device", parents=[common], help="this computer's memory, processor, disk and GPU",
    )
    p.set_defaults(func=_device)


def _device(args, out: Output) -> int:
    report = device_info()

    def human() -> None:
        d = report.device
        print(f"DocBox {report.version}")
        print(f"Memory     {d.ram_available_gb:.1f} GB free of {d.ram_total_gb:.1f} GB")
        print(f"Processor  {d.cpu_physical_cores} cores ({d.cpu_logical_cores} threads)")
        print(f"Disk       {d.disk_free_gb:.1f} GB free of {d.disk_total_gb:.1f} GB")
        memory = f", {d.gpu_memory_gb:g} GB" if d.gpu_memory_gb else ""
        supported = gpu.support()
        use = ("DocBox's engines can read on it: docbox engines gpu" if supported.usable
               else supported.reason)
        print(f"Graphics   {d.gpu_name or 'none found'}{memory} ({use})")
        print(f"System     {d.os_name} · {d.arch}")
        print(f"Data       {report.data_dir}")

    out.result(report, human)
    return 0
