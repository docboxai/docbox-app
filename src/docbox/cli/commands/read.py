"""docbox read <file|dir>... --model <id>"""

from __future__ import annotations

from pathlib import Path

from docbox.backend.schemas import ReadDetail
from docbox.cli.output import EXIT_ERROR, Output
from docbox.service import ocr
from docbox.service import settings as settings_service
from docbox.service.errors import Invalid, ServiceError


def register(sub, common) -> None:
    p = sub.add_parser(
        "read", parents=[common],
        help="read the text of images and PDFs, every page, and save it",
    )
    p.add_argument("paths", nargs="+", help="files or folders")
    p.add_argument("--model", "-m", help="model id (default: the default model setting)")
    p.add_argument("--format", "-f", choices=["txt", "md", "json", "pdf"], default="txt",
                   help="what to save (default txt; pdf is a searchable PDF)")
    p.add_argument("--out", "-o", type=Path,
                   help="folder to save into (default: the output folder setting)")
    p.add_argument("--recursive", "-r", action="store_true", help="include subfolders")
    p.add_argument("--print", dest="print_text", action="store_true",
                   help="also print the text (people mode)")
    p.add_argument("--lines", action="store_true",
                   help="with --json, include each line's confidence and position")
    p.add_argument("--ocr-all", action="store_true",
                   help="read every PDF page with the model, even pages that already "
                        "carry their own text (by default that text is used as-is)")
    p.set_defaults(func=_read)


def _jsonable(path: Path, result: ReadDetail | ServiceError, with_lines: bool) -> dict:
    if isinstance(result, ServiceError):
        return {"file": str(path), "error": {"code": result.code, "detail": result.detail}}
    pages = [
        {"page": i, "text": p.text, "source": p.source,
         **({"lines": p.lines} if with_lines else {})}
        for i, p in enumerate(result.pages, start=1)
    ]
    return {
        "file": str(path), "read_id": result.id, "model_id": result.model_id,
        "pages": pages, "seconds": result.seconds, "output_path": result.output_path,
    }


def _read(args, out: Output) -> int:
    model_id = args.model or settings_service.get_settings().default_model_id
    if not model_id:
        raise Invalid("Pick a model with --model (or set one: docbox settings set default-model)")
    files = ocr.collect_files(args.paths, recursive=args.recursive)
    if not files:
        raise Invalid("No images or PDFs found")

    results = []
    failed = 0
    for n, (path, result) in enumerate(
        ocr.read_files(files, model_id, args.format, args.out, use_pdf_text=not args.ocr_all),
        start=1,
    ):
        out.end_progress()
        if isinstance(result, ServiceError):
            failed += 1
            if not out.json:
                print(f"✗ {path}: {result.detail}")
        elif not out.json:
            pages = len(result.pages)
            own = sum(p.source == "pdf_text" for p in result.pages)
            note = f", {own} from the PDF's own text" if own else ""
            print(f"✓ {path} → {result.output_path} "
                  f"({pages} page{'s' if pages != 1 else ''}, {result.seconds:.1f} s{note})")
            if args.print_text:
                print(result.text.rstrip() + "\n")
        results.append(_jsonable(path, result, args.lines))
        if n < len(files):
            out.progress(f"reading {files[n].name} ({n + 1} of {len(files)})")

    out.result({"model_id": model_id, "files": results})
    return EXIT_ERROR if failed else 0
