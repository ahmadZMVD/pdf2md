"""PyMuPDF4LLM PDF-to-GitHub-Flavored-Markdown subprocess engine.

Contract with the Tauri conversion queue::

    python pdf_engine.py --input SOURCE.pdf --output TARGET.md

The process emits exactly one JSON object to stdout.  Expected failures have
distinct exit codes so the parent process can mark only the relevant queue
item as failed and continue with the next document.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_ENCRYPTED = 3
EXIT_ENGINE = 4
EXIT_RUNTIME = 5

# PyMuPDF4LLM normally emits an unquoted filesystem path.  The expression also
# accepts the angle-bracket form so a path containing spaces can be relinked.
IMAGE_LINK_PATTERN = re.compile(
    r"!\[[^\]]*\]\((?P<target><[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)"
)


def emit(payload: dict, code: int) -> None:
    """Emit the machine-readable result and terminate with *code*."""

    print(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    raise SystemExit(code)


def markdown_target_path(raw_target: str, output_dir: Path) -> Path:
    """Convert a Markdown image target to an absolute filesystem candidate."""

    target = raw_target[1:-1] if raw_target.startswith("<") and raw_target.endswith(">") else raw_target
    # Markdown generators can write backslashes even when running on Windows.
    candidate = Path(target.replace("\\", "/"))
    return candidate if candidate.is_absolute() else output_dir / candidate


def relink_images(markdown: str, images_dir: Path, output_dir: Path) -> tuple[str, int]:
    """Canonicalise extracted PNG names and make their links output-relative.

    A document is portable when the Markdown references
    ``OUTPUT_STEM_images/img_N.png`` rather than a temporary absolute path.
    The replacement is intentionally limited to image files written inside the
    current document's image directory; arbitrary Markdown links are untouched.
    """

    if not images_dir.is_dir():
        return markdown, 0

    canonical_dir = images_dir.resolve()
    name_by_source: dict[Path, str] = {}

    def rewrite(match: re.Match[str]) -> str:
        raw_target = match.group("target")
        try:
            source = markdown_target_path(raw_target, output_dir).resolve()
        except OSError:
            return match.group(0)

        if source.parent != canonical_dir or not source.is_file():
            return match.group(0)

        name = name_by_source.setdefault(source, f"img_{len(name_by_source) + 1}.png")
        rewritten = match.group(0).replace(raw_target, f"{images_dir.name}/{name}", 1)
        return rewritten.replace("![]", "![image]", 1)

    relinked = IMAGE_LINK_PATTERN.sub(rewrite, markdown)
    for source, name in name_by_source.items():
        destination = canonical_dir / name
        if source == destination:
            continue
        try:
            source.replace(destination)
        except OSError as error:
            raise RuntimeError(f"could not rename extracted image {source.name}: {error}") from error
    return relinked, len(name_by_source)


def convert(input_path: Path, output_path: Path) -> dict:
    """Convert *input_path* and atomically return JSON-ready conversion data."""

    try:
        import pymupdf
        import pymupdf4llm
    except ImportError as error:
        emit({"status": "runtime_missing", "error": str(error)}, EXIT_RUNTIME)

    document = pymupdf.open(str(input_path))
    try:
        if document.is_encrypted and not document.authenticate(""):
            emit({"status": "encrypted", "error": "password-protected PDF"}, EXIT_ENCRYPTED)
        page_count = document.page_count
    finally:
        document.close()

    images_dir = output_path.parent / f"{output_path.stem}_images"
    images_dir.mkdir(parents=True, exist_ok=True)
    markdown = pymupdf4llm.to_markdown(
        str(input_path),
        write_images=True,
        image_path=str(images_dir),
        image_format="png",
        show_progress=False,
    ).replace("\r\n", "\n")
    markdown, image_count = relink_images(markdown, images_dir, output_path.parent)

    if image_count == 0:
        try:
            if not any(images_dir.iterdir()):
                images_dir.rmdir()
                images_dir = None
        except OSError:
            # An undeletable empty directory is harmless and must not convert a
            # successful document into a failed queue item.
            pass

    output_path.write_text(markdown, encoding="utf-8")
    return {
        "status": "success",
        "output_path": str(output_path),
        "images_dir": str(images_dir) if images_dir else None,
        "image_count": image_count,
        "characters": len(markdown),
        "pages": page_count,
    }


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Convert a PDF to GFM Markdown.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.is_file():
        emit({"status": "usage_error", "error": "input file not found"}, EXIT_USAGE)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        emit({"status": "usage_error", "error": f"output directory unavailable: {error}"}, EXIT_USAGE)

    started = time.perf_counter()
    try:
        payload = convert(input_path, output_path)
    except SystemExit:
        raise
    except Exception as error:  # The queue consumes structured failures only.
        emit({"status": "failed", "error": f"{type(error).__name__}: {error}"}, EXIT_ENGINE)

    payload["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    emit(payload, EXIT_OK)


if __name__ == "__main__":
    main(sys.argv[1:])
