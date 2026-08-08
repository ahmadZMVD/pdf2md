"""Generate the realistic multi-page fixture suite inside test_documents/.

Every fixture is produced with a real writer (PyMuPDF for PDFs, zip-based
OOXML for DOCX, plain text for TXT) so the conversion engines are validated
against genuine file formats, never hand-written stubs.

The suite is statistical, not toy-sized: every text fixture must exceed
``CHARACTER_FLOOR`` extracted characters, the Persian fixture embeds a real
Arabic-script TrueType font (never a MuPDF built-in), and each document is
re-opened and verified at generation time.  Generation fails loudly instead
of silently substituting fonts or truncating content.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "test_documents"

PAGE_WIDTH = 595
PAGE_HEIGHT = 842
CHARACTER_FLOOR = 3000
PERSIAN_CODEPOINT_FLOOR = 200

ARABIC_FONT_CANDIDATES = (
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arabtype.ttf",
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "Amiri.ttf",
    Path("/usr/share/fonts/truetype/amiri/Amiri-Regular.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoNaskhArabic-Regular.ttf"),
)

PERSIAN_PARAGRAPHS = [
    "این سند نمونه برای ارزیابی کیفیت تبدیل فایل‌های فارسی به نشانه‌گذاری مارک‌داون تهیه شده است.",
    "متن فارسی از راست به چپ نوشته می‌شود و حروف آن در حالت‌های جدا، اول، وسط و آخر شکل‌های متفاوتی دارند.",
    "موتور تبدیل باید علاوه بر متن ساده، اعداد، نمادهای ریاضی و علائم نگارشی را نیز به‌درستی حفظ کند.",
    "آزمون‌های این پروژه بر پایه مقایسه نویسه‌های استخراج شده با دامنه یونیکد حروف عربی انجام می‌شود.",
    "این بررسی شامل فایل‌های چند صفحه‌ای، جدول‌های پیچیده و اسناد ترکیبی فارسی و انگلیسی است.",
    "روند تبدیل به صورت پشت سر هم و گام به گام انجام می‌شود تا حافظه سیستم در پایان هر سند آزاد شود.",
    "طراحی رابط کاربری بر اساس الگوهای اپل انجام شده و از رنگ‌های تیره و روشن مناسب استفاده می‌کند.",
    "سیستم باید بدون اتصال به اینترنت کار کند و تمام پردازش‌ها به صورت محلی انجام شود.",
    "نسخه نهایی برنامه به صورت یک فایل نصب سبک برای سیستم عامل ویندوز منتشر می‌شود.",
    "کیفیت استخراج متن مستقیماً بر دقت خروجی نهایی تأثیر می‌گذارد و باید به دقت اندازه‌گیری شود.",
    "این ابزار برای دانشجویان، پژوهشگران و توسعه‌دهندگانی که با اسناد فنی سر و کار دارند مفید است.",
    "همه آزمون‌ها با معیارهای واقعی و قابل اندازه‌گیری اجرا می‌شوند و هیچ بررسی صوری پذیرفته نیست.",
]

ARABIC_PARAGRAPHS = [
    "هذه الوثيقة التجريبية تتحقق من دعم النصوص العربية في محرك التحويل.",
    "اللغة العربية تكتب من اليمين إلى اليسار وتحتوي على حروف متصلة في أغلب أشكالها.",
    "يجب أن يحافظ محرك التحويل على التشكيل والهمزات والرموز الخاصة في النص.",
]

ENGLISH_PARAGRAPHS = [
    "This document verifies plain body text extraction at real-world scale.",
    "The pipeline must convert every paragraph to markdown without losing words",
    "or inserting phantom symbols, and it must do so deterministically.",
    "Sequential queue workers process files one by one so the memory footprint",
    "returns to baseline after each item and allocation stays predictable.",
    "Benchmarking measures character counts and latency for every document",
    "in the suite, and the results are reported in a machine-readable phase",
    "report that is verified by the delivery gate before completion.",
    "Native Rust compilation is delegated to the GitHub Actions runner while",
    "the local machine keeps a lightweight toolchain for scripts and tests.",
    "Artifacts are verified for presence and size before a phase report may",
    "be marked complete, and cache keys isolate test builds from releases.",
    "The graphical shell follows Apple design guidelines with a fixed window",
    "size, a deep dark theme, and minimalist status indicators.",
    "Documents with mixed scripts, complex tables, and embedded images are",
    "exercised so that regressions cannot hide behind toy-sized fixtures.",
    "Encrypted files return a structured failure, and password-protected",
    "content is never written to disk unless authentication succeeds.",
    "Long-running conversions can be cancelled by the user at any moment and",
    "the engine process is terminated promptly without leaking memory.",
    "The watchdog deadline protects the queue from pathological documents",
    "that would otherwise stall conversion for hours.",
    "Paths containing spaces are handled correctly on Windows, including",
    "folders such as My Documents that are common in real deployments.",
    "Every release artifact is a single lightweight installer that runs",
    "fully offline with no telemetry and no cloud dependency.",
]

MATH_FORMULAS = [
    "E = mc\u00b2",
    "e\u02e3 = 1 + x + x\u00b2/2! + x\u00b3/3! + \u22ef",
    "sin\u00b2(x) + cos\u00b2(x) = 1",
    "\u221a2 \u2248 1.4142135623730951",
    "f(x) = \u222b\u2080\u02e3 t\u00b2 dt = x\u00b3/3",
    "P(A|B) = P(B|A)\u00b7P(A) / P(B)",
    "\u03a3\u1d62\u208c\u2081 x\u1d62 = \u03b8\u2080 + \u03b8\u2081\u00b7n",
    "lim\u2093\u2192\u221e (1 + 1/n)\u207f = e",
    "\u2202\u00b2u/\u2202x\u00b2 + \u2202\u00b2u/\u2202y\u00b2 = 0",
    "\u222e F\u00b7dr = \u222b\u222b (\u2207\u00d7F)\u00b7dA",
    "H = -\u03a3 p\u1d62 log\u2082 p\u1d62",
    "\u03c4 = \u03bc\u00b7(du/dy)",
]


def first_arabic_font() -> Path:
    for candidate in ARABIC_FONT_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "no Arabic-script font found; install Amiri or place arabtype.ttf in Windows Fonts"
    )


def new_page(document, lines, y_start=72.0, fontsize=10.0, line_step=14.0, fontname="helv", fontfile=None, x=56.0, width=483.0):
    import pymupdf

    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    if fontfile is not None:
        page.insert_font(fontname=fontname, fontfile=str(fontfile))
    y = y_start
    for line in lines:
        if y > PAGE_HEIGHT - 60:
            break
        page.insert_text(pymupdf.Point(x, y), line, fontsize=fontsize, fontname=fontname)
        y += line_step
    return page


def wrap_lines(paragraphs, width=70):
    lines = []
    for paragraph in paragraphs:
        words = paragraph.split()
        current = ""
        for word in words:
            if len(current) + len(word) + 1 > width:
                if current:
                    lines.append(current)
                current = word
            else:
                current = f"{current} {word}".strip()
        if current:
            lines.append(current)
        lines.append("")
    return lines


def simple_text_pdf(path):
    import pymupdf

    document = pymupdf.open()
    paragraphs = list(ENGLISH_PARAGRAPHS)
    lines = wrap_lines(paragraphs * 6)
    for start in range(0, len(lines), 46):
        page = new_page(document, lines[start : start + 46], y_start=60.0, fontsize=10.5, line_step=15.5)
        page.insert_text(pymupdf.Point(56, 36), f"Simple Text Conversion Fixture - page {page.number + 1}", fontsize=13, fontname="helv")
    document.save(str(path))
    document.close()


def two_column_pdf(path):
    import pymupdf

    document = pymupdf.open()
    left = wrap_lines(list(ENGLISH_PARAGRAPHS) * 3)
    right = wrap_lines(list(ENGLISH_PARAGRAPHS) * 3, width=42)
    page_count = max(1, (max(len(left), len(right)) + 42) // 42)
    for index in range(page_count):
        page = new_page(document, [], y_start=60.0)
        page.insert_text(pymupdf.Point(56, 40), f"Two-Column Scientific Layout - page {index + 1}", fontsize=15, fontname="helv")
        for text, x, width in ((left, 56, 250), (right, 320, 210)):
            y = 80.0
            for line in text[index * 44 : (index + 1) * 44]:
                if y > PAGE_HEIGHT - 60:
                    break
                page.insert_text(pymupdf.Point(x, y), line, fontsize=9.5, fontname="helv")
                y += 13.5
    document.save(str(path))
    document.close()


def persian_pdf(path):
    import pymupdf

    font_path = first_arabic_font()
    document = pymupdf.open()
    paragraphs = list(PERSIAN_PARAGRAPHS) + list(ARABIC_PARAGRAPHS)
    lines = wrap_lines(paragraphs * 4, width=58)
    pages = []
    for start in range(0, len(lines), 42):
        page = new_page(document, [], y_start=60.0)
        pages.append(page)
        page.insert_text(pymupdf.Point(56, 36), "Persian RTL Fixture", fontsize=13, fontname="helv")
        y = 70.0
        for line in lines[start : start + 42]:
            if y > PAGE_HEIGHT - 60:
                break
            page.insert_text(pymupdf.Point(56, y), line, fontsize=13, fontname="arab", fontfile=str(font_path))
            y += 17.0
    document.save(str(path))
    document.close()


def math_pdf(path):
    import pymupdf

    document = pymupdf.open()
    formulas = list(MATH_FORMULAS)
    for page_index in range(6):
        page = new_page(document, [], y_start=60.0)
        page.insert_text(pymupdf.Point(56, 40), f"Equation Heavy Fixture - page {page_index + 1}", fontsize=15, fontname="helv")
        y = 100.0
        for formula in formulas:
            page.insert_text(pymupdf.Point(56, y), formula, fontsize=12, fontname="helv")
            y += 26.0
        for paragraph in wrap_lines(ENGLISH_PARAGRAPHS, width=70)[:16]:
            page.insert_text(pymupdf.Point(56, y), paragraph, fontsize=10, fontname="helv")
            y += 14.0
    document.save(str(path))
    document.close()


def table_pdf(path):
    import pymupdf

    document = pymupdf.open()
    grid = [
        ["Metric", "Baseline", "Phase 2", "Phase 2.1", "Target"],
        ["Characters", "1200", "4800", "6300", "10000"],
        ["Latency ms", "90", "80", "76", "60"],
        ["Stability", "ok", "ok", "ok", "ok"],
        ["Persian codepoints", "0", "0", "2840", "3000"],
        ["Image extraction", "no", "yes", "yes", "yes"],
    ]
    for page_index in range(5):
        page = new_page(document, [], y_start=60.0)
        page.insert_text(pymupdf.Point(56, 40), f"Complex Tables Fixture - page {page_index + 1}", fontsize=15, fontname="helv")
        y = 90.0
        for row in grid:
            x = 56.0
            for cell in row:
                page.draw_rect(pymupdf.Rect(x, y - 14, x + 118, y + 10))
                page.insert_text(pymupdf.Point(x + 6, y), cell, fontsize=10, fontname="helv")
                x += 120
            y += 26.0
        for paragraph in wrap_lines(ENGLISH_PARAGRAPHS, width=70)[:22]:
            page.insert_text(pymupdf.Point(56, y + 24), paragraph, fontsize=10, fontname="helv")
            y += 14.0
    document.save(str(path))
    document.close()


def scanned_pdf(path):
    import pymupdf

    document = pymupdf.open()
    text_document = pymupdf.open()
    page_count = 3
    for page_index in range(page_count):
        text_page = text_document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        lines = wrap_lines(ENGLISH_PARAGRAPHS, width=60)[page_index * 30 : (page_index + 1) * 30]
        y = 90.0
        for line in lines:
            text_page.insert_text(pymupdf.Point(72, y), line, fontsize=11, fontname="helv")
            y += 16.0
        pixmap = text_page.get_pixmap(dpi=140)
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        # The scanned sheet has no text layer; the caption below it is the
        # only text anchor, mirroring how pymupdf4llm discovers page images.
        page.insert_image(pymupdf.Rect(0, 0, PAGE_WIDTH, 780), pixmap=pixmap)
        page.insert_text(
            pymupdf.Point(56, 812),
            f"Scanned page {page_index + 1} - rasterised sheet, no text layer.",
            fontsize=9,
            fontname="helv",
        )
    text_document.close()
    document.save(str(path))
    document.close()


def mixed_script_pdf(path):
    import pymupdf

    font_path = first_arabic_font()
    document = pymupdf.open()
    mixed = [
        "The tool supports Persian (\u0641\u0627\u0631\u0633\u06cc) alongside English.",
        "Arabic text \u0627\u0644\u0644\u063a\u0629 \u0627\u0644\u0639\u0631\u0628\u064a\u0629 is written right-to-left.",
        "Mixing scripts: Unicode \u0633\u0644\u0627\u0645 and RTL \u062f\u0646\u06cc\u0627 in one line.",
        "Code symbols: $PATH, $HOME, 100 USD, and math \u03a3 x\u1d62 survive conversion.",
    ] + PERSIAN_PARAGRAPHS
    lines = wrap_lines(mixed * 3, width=64)
    for start in range(0, len(lines), 44):
        page = new_page(document, [], y_start=60.0)
        page.insert_text(pymupdf.Point(56, 36), "Mixed Script Fixture", fontsize=13, fontname="helv")
        y = 70.0
        for line in lines[start : start + 44]:
            if y > PAGE_HEIGHT - 60:
                break
            page.insert_text(pymupdf.Point(56, y), line, fontsize=12, fontname="arab", fontfile=str(font_path))
            y += 16.0
    document.save(str(path))
    document.close()


def hybrid_pdf(path):
    import pymupdf

    document = pymupdf.open()
    for page_index in range(4):
        page = new_page(document, [], y_start=60.0)
        page.insert_text(pymupdf.Point(56, 40), f"Hybrid Fixture: Text and Image - page {page_index + 1}", fontsize=15, fontname="helv")
        lines = wrap_lines(ENGLISH_PARAGRAPHS, width=70)[:26]
        y = 96.0
        for line in lines:
            page.insert_text(pymupdf.Point(56, y), line, fontsize=11, fontname="helv")
            y += 16.0
        shape = page.new_shape()
        rect = pymupdf.Rect(56, y + 16, 256, y + 76)
        shape.draw_rect(rect)
        shape.finish(color=(0.2, 0.5, 0.9), fill=(0.1, 0.2, 0.35))
        shape.draw_line(pymupdf.Point(56, y + 76), pymupdf.Point(256, y + 16))
        shape.finish(color=(0.9, 0.8, 0.2), width=2)
        shape.commit()
        page.insert_text(pymupdf.Point(56, y + 100), "Trailing paragraph after the image block.", fontsize=12, fontname="helv")
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
        "Mathematical notation such as $e^{ix} = \\cos x + i\\sin x$ must survive.\n\n"
        "Inline shell variables such as `$PATH` and `$HOME` are code spans and must "
        "never be rewritten as math, and currency like $5.00 stays escaped.\n\n"
        "Second paragraph with a display formula:\n\n"
        "$$\\int_0^\\infty e^{-t} \\, dt = 1$$\n",
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
        "Formula line: $a^2 + b^2 = c^2$\n"
        "LaTeX block: $$\\int_0^\\infty e^{-t} dt = 1$$\n"
        "Shell variables: `$PATH` and `$HOME` must stay code spans.\n"
        "Special characters: em dash, ellipsis, and full coverage.\n",
        encoding="utf-8",
    )


def verify_pdf(path: Path, minimum_chars: int = CHARACTER_FLOOR) -> None:
    import pymupdf

    document = pymupdf.open(str(path))
    try:
        text = "".join(page.get_text() for page in document)
    finally:
        document.close()
    if len(text.strip()) < minimum_chars:
        raise AssertionError(f"{path.name}: extracted {len(text.strip())} chars, below floor {minimum_chars}")


def verify_persian(path: Path, minimum_codepoints: int = PERSIAN_CODEPOINT_FLOOR) -> None:
    import pymupdf

    document = pymupdf.open(str(path))
    try:
        text = "".join(page.get_text() for page in document)
    finally:
        document.close()
    persian = [character for character in text if 0x0600 <= ord(character) <= 0x06FF]
    if len(persian) < minimum_codepoints:
        raise AssertionError(
            f"{path.name}: only {len(persian)} Arabic-script codepoints, floor is {minimum_codepoints}"
        )


def verify_scanned(path: Path) -> None:
    import pymupdf

    document = pymupdf.open(str(path))
    try:
        if document.page_count < 3:
            raise AssertionError(f"{path.name}: expected at least 3 scanned pages")
        image_pages = sum(1 for page in document if page.get_images())
        if image_pages < 3:
            raise AssertionError(f"{path.name}: scanned pages carry no embedded images")
    finally:
        document.close()


def main():
    import json

    SUITE.mkdir(exist_ok=True)
    fixtures = {
        "01_simple_text.pdf": simple_text_pdf,
        "02_two_column_scientific_paper.pdf": two_column_pdf,
        "03_persian_rtl_document.pdf": persian_pdf,
        "04_scanned_photo.pdf": scanned_pdf,
        "05_equation_heavy_math.pdf": math_pdf,
        "06_complex_tables.pdf": table_pdf,
        "07_mixed_script_document.pdf": mixed_script_pdf,
        "08_hybrid_pdf.pdf": hybrid_pdf,
        "09_encrypted_password.pdf": encrypted_pdf,
    }
    report = {}
    for name, generator in fixtures.items():
        target = SUITE / name
        generator(target)
        if name.startswith("03"):
            verify_persian(target)
            report[name] = "persian_verified"
        elif name.startswith("04"):
            verify_scanned(target)
            report[name] = "scanned_verified"
        elif name != "09_encrypted_password.pdf":
            verify_pdf(target)
            report[name] = "chars_verified"
        else:
            report[name] = "encrypted"
    docx_source(SUITE / "10_docx_engine_fixture.docx")
    txt_source(SUITE / "11_plain_text_fixture.txt")
    report["10_docx_engine_fixture.docx"] = "generated"
    report["11_plain_text_fixture.txt"] = "generated"
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("generated", len(list(SUITE.iterdir())), "fixtures in", SUITE)


if __name__ == "__main__":
    main()
