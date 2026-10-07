from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _bench_fakes():
    # Imported on use, not at collection: importing registers the fake models, and they
    # must not leak into other test folders' model listings.
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import bench_fakes

    return bench_fakes


@pytest.fixture()
def fakes(data_dir, monkeypatch):
    """The fake models, registered here and in every worker process."""
    monkeypatch.setenv("DOCBOX_PRELOAD", "bench_fakes")
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join(filter(None, [str(HERE), os.environ.get("PYTHONPATH")]))
    )
    bench_fakes = _bench_fakes()
    bench_fakes.register()
    yield bench_fakes
    bench_fakes.unregister()


@pytest.fixture()
def docs(tmp_path: Path) -> Path:
    """invoice.png (one page, whole reference) and report.pdf (two pages, page 2 reference
    only), plus scan.png without any reference."""
    bench_fakes = _bench_fakes()
    d = tmp_path / "docs"
    d.mkdir()
    bench_fakes.page_image(1).save(d / "invoice.png")
    (d / "invoice.gt.txt").write_text(bench_fakes.TEXTS[1] + "\n")
    p1, p2 = bench_fakes.page_image(1).convert("RGB"), bench_fakes.page_image(2).convert("RGB")
    p1.save(d / "report.pdf", save_all=True, append_images=[p2])
    (d / "report.p2.gt.txt").write_text(bench_fakes.TEXTS[2])
    bench_fakes.page_image(1).save(d / "scan.png")
    return d
