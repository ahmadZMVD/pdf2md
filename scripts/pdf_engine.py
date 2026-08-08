"""PyMuPDF4LLM PDF-to-GitHub-Flavored-Markdown subprocess engine.

Contract with the Tauri conversion queue::

    python pdf_engine.py --input SOURCE.pdf --output TARGET.md
                         [--timeout SECONDS] [--max-pages COUNT]

The process emits exactly one JSON object to stdout.  Expected failures have
distinct exit codes so the parent process can mark only the relevant queue
item as failed and continue with the next document.

Robustness guarantees:

* The conversion runs inside a watchdog thread with a hard deadline.  If the
  upstream library hangs (pathological PDF, decompression bomb), the process
  terminates itself with ``os._exit`` so the queue can never be stalled.
* Extracted images are staged in a temporary directory and only moved next to
  the output document afterwards.  This bypasses ``pymupdf4llm.md_path``,
  which sanitizes spaces in the *save* target while creating the directory
  with the original name, a deterministic ``FzErrorSystem code=2`` failure
  for any output folder containing a space.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_ENCRYPTED = 3
EXIT_ENGINE = 4
EXIT_RUNTIME = 5

DEFAULT_DEADLINE_SECONDS = 300.0
DEFAULT_MAX_PAGES = 2000

# PyMuPDF4LLM normally emits an unquoted filesystem path.  The expression also
# accepts the angle-bracket form so a path containing spaces can be relinked.
IMAGE_LINK_PATTERN = re.compile(
    r"!\[[^\]]*\]\((?P<target><[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)"
)

# Characters that break an unquoted Markdown link target when they originate
# from our own sanitized output stems (spaces, parentheses, brackets).
LINK_ENCODING = ((" ", "%20"), ("(", "%28"), (")", "%29"), ("[", "%5B"), ("]", "%5D"))

# Character substitutions applied by pymupdf4llm.helpers.utils.md_path to the
# markdown reference AND the pix.save() target.  Kept only to pre-create the
# sanitized directory when the staging location itself contains one of these
# characters (belt-and-braces; the staging directory is normally space-free).
MD_PATH_REPLACEMENTS = (
    ("(", "-"),
    (")", "-"),
    ("[", "-"),
    ("]", "-"),
    (" ", "_"),
    ("\u2010", "-"),
    ("\u2011", "-"),
    ("\u2012", "-"),
    ("\u2013", "-"),
    ("\u2014", "-"),
    ("\u2015", "-"),
    ("\u2212", "-"),
)


def emit(payload: dict, code: int) -> None:
    """Emit the machine-readable result and terminate with *code*."""

    print(json.dumps(payload, ensure_ascii=False), flush=True)
    raise SystemExit(code)


def markdown_target_path(raw_target: str, output_dir: Path) -> Path:
    """Convert a Markdown image target to an absolute filesystem candidate."""

    target = raw_target[1:-1] if raw_target.startswith("<") and raw_target.endswith(">") else raw_target
    # Markdown generators can write backslashes even when running on Windows.
    candidate = Path(target.replace("\\", "/"))
    return candidate if candidate.is_absolute() else output_dir / candidate


def sanitized_target(raw_target: str, output_dir: Path) -> Path:
    """Resolve *raw_target* as if it had been written by ``md_path``.

    ``md_path`` may sanitize the reference string (spaces, brackets, dashes)
    while saving the pixel data under that same sanitized string.  The engine
    therefore accepts links pointing at either the real staging directory or
    its sanitized twin.
    """

    target = raw_target[1:-1] if raw_target.startswith("<") and raw_target.endswith(">") else raw_target
    candidate = Path(target.replace("\\", "/"))
    if not candidate.is_absolute():
        candidate = output_dir / candidate
    sanitized = str(candidate)
    for old, new in MD_PATH_REPLACEMENTS:
        sanitized = sanitized.replace(old, new)
    return Path(sanitized).resolve()


def relink_images(markdown: str, staging_dir: Path, images_dir: Path, output_dir: Path) -> tuple[str, int]:
    """Canonicalise extracted PNG names and make their links output-relative.

    A document is portable when the Markdown references
    ``OUTPUT_STEM_images/img_N.png`` rather than a temporary absolute path.
    The replacement is intentionally limited to image files written inside the
    current document's staging directory; arbitrary Markdown links are
    untouched.  Every moved image is renamed from the files that actually
    exist on disk, so no upstream naming assumption can leak into the output.
    """

    if not staging_dir.is_dir():
        return markdown, 0

    staging = staging_dir.resolve()
    canonical_dir = images_dir.resolve()
    name_by_source: dict[Path, str] = {}

    def rewrite(match: re.Match[str]) -> str:
        raw_target = match.group("target")
        try:
            source = markdown_target_path(raw_target, output_dir).resolve()
            sanitized_source = sanitized_target(raw_target, output_dir)
        except OSError:
            return match.group(0)

        if source.parent not in (staging, sanitized_source.parent) or not source.is_file():
            return match.group(0)
        canonical_dir.mkdir(parents=True, exist_ok=True)

        name = name_by_source.setdefault(source, f"img_{len(name_by_source) + 1}.png")
        relative_target = f"{images_dir.name}/{name}"
        for old, new in LINK_ENCODING:
            relative_target = relative_target.replace(old, new)
        rewritten = match.group(0).replace(raw_target, relative_target, 1)
        return rewritten.replace("![]", "![image]", 1)

    relinked = IMAGE_LINK_PATTERN.sub(rewrite, markdown)
    for source, name in name_by_source.items():
        destination = canonical_dir / name
        if source == destination:
            continue
        try:
            shutil.move(str(source), str(destination))
        except OSError as error:
            raise RuntimeError(f"could not move extracted image {source.name}: {error}") from error
    return relinked, len(name_by_source)


def convert(input_path: Path, output_path: Path, max_pages: int) -> dict:
    """Convert *input_path* and return JSON-ready conversion data.

    Runs inside the caller's watchdog thread; must not call :func:`emit`
    for the terminal success/failure payloads (the main thread owns them).
    """

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
        if page_count > max_pages:
            emit(
                {
                    "status": "failed",
                    "error": f"document has {page_count} pages, exceeding the {max_pages} page conversion limit",
                },
                EXIT_ENGINE,
            )
    finally:
        document.close()

    images_dir = output_path.parent / f"{output_path.stem}_images"
    staging_root = Path(tempfile.mkdtemp(prefix="pdf2md_staging_"))
    staging_dir = staging_root / "images"
    staging_dir.mkdir(exist_ok=True)
    # If the temporary directory itself contains characters that md_path
    # sanitizes (e.g. a user profile with a space), pre-create the sanitized
    # twin so pix.save() can never target a non-existent directory.
    sanitized_staging = Path(sanitized_target(str(staging_dir), output_path.parent))
    if sanitized_staging != staging_dir.resolve():
        sanitized_staging.mkdir(parents=True, exist_ok=True)
    try:
        markdown = pymupdf4llm.to_markdown(
            str(input_path),
            write_images=True,
            image_path=str(staging_dir),
            image_format="png",
            show_progress=False,
        ).replace("\r\n", "\n")
        markdown, image_count = relink_images(markdown, staging_dir, images_dir, output_path.parent)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

    if image_count == 0:
        try:
            if images_dir.is_dir() and not any(images_dir.iterdir()):
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
    parser.add_argument("--timeout", type=float, default=DEFAULT_DEADLINE_SECONDS)
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
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
    result: dict = {}
    errors: list[BaseException] = []

    def run() -> None:
        try:
            result["payload"] = convert(input_path, output_path, max_pages=args.max_pages)
        except BaseException as error:  # noqa: BLE001 - collected by the watchdog
            errors.append(error)

    worker = threading.Thread(target=run, name="pdf2md-conversion-watchdog", daemon=True)
    worker.start()
    worker.join(timeout=args.timeout)
    if worker.is_alive():
        # The upstream conversion is stuck.  os._exit bypasses atexit/finally
        # and interpreter shutdown so even a hang inside native C code cannot
        # delay termination of the process.
        print(
            json.dumps(
                {
                    "status": "timeout",
                    "error": f"conversion exceeded the {args.timeout:g} second timeout",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        os._exit(EXIT_RUNTIME)
    if errors:
        error = errors[0]
        if isinstance(error, SystemExit):
            # Structured failures raised by convert() (encrypted, limits).
            raise error
        emit({"status": "failed", "error": f"{type(error).__name__}: {error}"}, EXIT_ENGINE)

    payload = result["payload"]
    payload["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    emit(payload, EXIT_OK)


if __name__ == "__main__":
    main(sys.argv[1:])
