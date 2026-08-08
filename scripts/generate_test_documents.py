"""Generate the real-world fixture suite inside test_documents/.

Every fixture is produced with a real writer (PyMuPDF for PDFs, zip-based
OOXML for DOCX, plain text for TXT) so the conversion engines are validated
against genuine file formats, never hand-written stubs.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "test_documents"


def simple_text_pdf(path):
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(pymupdf.Point(56, 72), "Simple Text Conversion Fixture", fontsize=14, fontname="helv")
    lines = [
        "This document verifies plain body text extraction.",
        "The pipeline must convert every paragraph to markdown",
        "without losing words or inserting phantom symbols.",
        "",
        "Sequential queue workers process files one by one so the",
        "memory footprint returns to baseline after each item.",
    ]
    y = 104.0
    for line in lines:
        page.insert_text(pymupdf.Point(56, y), line, fontsize=11, fontname="helv")
        y += 16
    document.save(str(path))
    document.close()


def two_column_pdf(path):
    import pymupdf

    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text(pymupdf.Point(56, 60), "Two-Column Scientific Layout", fontsize=16, fontname="helv")
    left = [
        "Column A discusses deterministic queues.",
        "Each file is processed strictly one at a time,",
        "so allocation patterns remain predictable",
        "and the worker releases memory after use.",
        "",
        "Benchmarking measures character counts and",
        "latency for every document in the suite.",
    ]
    right = [
        "Column B discusses cloud builds.",
        "Native Rust compilation is delegated to the",
        "GitHub Actions windows-latest runner while the",
        "local machine keeps its lightweight toolchain.",
        "",
        "Artifacts are verified for presence and size",
        "before a phase report may be marked complete.",
    ]
    y = 100.0
    for line in left:
        page.insert_text(pymupdf.Point(56, y), line, fontsize=10, fontname="helv")
        y += 14
    y = 100.0
    for line in right:
        page.insert_text(pymupdf.Point(320, y), line, fontsize=10, fontname="helv")
        y += 14
    document.save(str(path))
    document.close()


def persian_pdf(path):
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(pymupdf.Point(56, 72), "Persian RTL Fixture", fontsize=14, fontname="helv")
    page.insert_text(pymupdf.Point(56, 104), "This fixture represents right-to-left scripts.", fontsize=12, fontname="helv")
    try:
        page.insert_text(pymupdf.Point(56, 140), "\u0633\u0644\u0627\u0645 \u062f\u0646\u06cc\u0627", fontsize=16, fontname="tiro")
    except Exception:
        pass
    document.save(str(path))
    document.close()


def math_pdf(path):
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(pymupdf.Point(56, 60), "Equation Heavy Fixture", fontsize=16, fontname="helv")
    formulas = [
        "E = mc2",
        "ex = 1 + x + x2/2! + x3/3! + ...",
        "sin(x)2 + cos(x)2 = 1",
        "sqrt(2) = 1.41421356...",
        "f(x) = integral(0, x) t2 dt = x3/3",
        "P(A given B) = P(B given A) P(A) / P(B)",
    ]
    y = 100.0
    for formula in formulas:
        page.insert_text(pymupdf.Point(56, y), formula, fontsize=12, fontname="helv")
        y += 26
    document.save(str(path))
    document.close()


def table_pdf(path):
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(pymupdf.Point(56, 60), "Complex Tables Fixture", fontsize=16, fontname="helv")
    rows = [
        ("Metric", "Baseline", "Phase 2"),
        ("Characters", "1200", "4800"),
        ("Latency ms", "90", "80"),
        ("Stability", "ok", "ok"),
    ]
    y = 110.0
    for row in rows:
        x = 56.0
        for cell in row:
            page.insert_text(pymupdf.Point(x, y), cell, fontsize=11, fontname="helv")
            x += 130
        y += 24
    document.save(str(path))
    document.close()


def hybrid_pdf(path):
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(pymupdf.Point(56, 60), "Hybrid Fixture: Text and Image", fontsize=16, fontname="helv")
    page.insert_text(pymupdf.Point(56, 96), "The block below the heading is a drawn image that the", fontsize=12, fontname="helv")
    page.insert_text(pymupdf.Point(56, 114), "engine must extract into the images folder.", fontsize=12, fontname="helv")
    shape = page.new_shape()
    shape.draw_rect(pymupdf.Rect(56, 150, 256, 290))
    shape.finish(color=(0.2, 0.5, 0.9), fill=(0.1, 0.2, 0.35))
    shape.draw_line(pymupdf.Point(56, 290), pymupdf.Point(256, 150))
    shape.finish(color=(0.9, 0.8, 0.2), width=2)
    shape.commit()
    page.insert_text(pymupdf.Point(56, 330), "Trailing paragraph after the image block.", fontsize=12, fontname="helv")
    document.save(str(path))
    document.close()


def encrypted_pdf(path):
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(pymupdf.Point(56, 72), "Encrypted fixture body.", fontsize=12, fontname="helv")
    document.save(
        str(path),
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw="phase2",
        owner_pw="owner2",
    )
    document.close()


def docx_source(path):
    import subprocess
    import sys
    import tempfile

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from tool_paths import resolve_tool

    resolution = resolve_tool("pandoc")
    if resolution["status"] == "unavailable":
        raise RuntimeError("pandoc is required to build the DOCX fixture")
    source = Path(tempfile.gettempdir()) / "pdf2md_docx_source.md"
    source.write_text(
        "# DOCX Engine Fixture\n\n"
        "Pandoc converts this document to GitHub flavored markdown.\n\n"
        "Mathematical notation such as $e{ix} = \\cos x + i\\sin x$ must survive.\n",
        encoding="utf-8",
    )
    subprocess.run(
        [resolution["path"], "-f", "markdown", "-t", "docx", "-o", str(path), str(source)],
        check=True,
        capture_output=True,
    )


def txt_source(path):
    path.write_text(
        "Plain Text Fixture\n"
        "==================\n\n"
        "Pandoc reads this file as markdown-ish text and emits GFM.\n\n"
        "Formula line: $a2 + b2 = c2$\n"
        "LaTeX block: $$\\int_0\\infty e{-t} dt = 1$$\n"
        "Special characters: em dash, ellipsis, and full coverage.\n",
        encoding="utf-8",
    )


def main():
    SUITE.mkdir(exist_ok=True)
    simple_text_pdf(SUITE / "01_simple_text.pdf")
    two_column_pdf(SUITE / "02_two_column_scientific_paper.pdf")
    persian_pdf(SUITE / "03_persian_rtl_document.pdf")
    math_pdf(SUITE / "05_equation_heavy_math.pdf")
    table_pdf(SUITE / "06_complex_tables.pdf")
    hybrid_pdf(SUITE / "08_hybrid_pdf.pdf")
    encrypted_pdf(SUITE / "09_encrypted_password.pdf")
    docx_source(SUITE / "10_docx_engine_fixture.docx")
    txt_source(SUITE / "11_plain_text_fixture.txt")
    print("generated", len(list(SUITE.iterdir())), "fixtures in", SUITE)


if __name__ == "__main__":
    main()
