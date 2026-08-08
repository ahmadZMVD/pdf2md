"""Execution-based Phase 2 tests for conversion engines, path contracts, and
the statistical benchmark dataset (Phase 2.1)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fs_utils  # noqa: E402
import tool_paths  # noqa: E402

CHARACTER_FLOOR = 3000
PERSIAN_CODEPOINT_FLOOR = 200
MATH_FILTER = SCRIPTS / "filters" / "math_preserve.lua"


def run_engine(source: Path, destination: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "pdf_engine.py"),
            "--input",
            str(source),
            "--output",
            str(destination),
            "--timeout",
            "60",
            *extra,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=90,
    )


def extracted_text(path: Path) -> str:
    import pymupdf

    document = pymupdf.open(str(path))
    try:
        return "".join(page.get_text() for page in document)
    finally:
        document.close()


class Phase2ExecutionTests(unittest.TestCase):
    def test_bundled_tool_resolution_precedes_system_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            resource_dir = Path(temporary) / "resources" / "bin"
            resource_dir.mkdir(parents=True)
            portable_python = resource_dir / ("python.exe" if tool_paths.os.name == "nt" else "python")
            portable_python.write_bytes(b"portable")
            portable_python.chmod(0o755)
            with patch.object(tool_paths, "RESOURCE_DIRS", (resource_dir,)), patch.object(
                tool_paths.shutil, "which", return_value="C:/system/python.exe"
            ):
                resolution = tool_paths.resolve_tool("python")
            self.assertEqual(resolution["status"], "bundled")
            self.assertEqual(Path(resolution["path"]), portable_python)
            self.assertEqual(resolution["source"], "resources_bin")

    def test_missing_tool_resolution_is_structured_not_exceptional(self) -> None:
        with patch.object(tool_paths, "RESOURCE_DIRS", (Path("not-a-resource-directory"),)), patch.object(
            tool_paths.shutil, "which", return_value=None
        ):
            resolution = tool_paths.resolve_tool("absent-tool")
        self.assertEqual(resolution, {"status": "unavailable", "path": None, "source": None})

    def test_incremental_output_paths_skip_disk_and_batch_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "report.md").write_text("existing", encoding="utf-8")
            reserved = {str(directory / "report_1.md")}
            next_path = fs_utils.incremental_output_path(directory, "report", ".md", reserved)
            self.assertEqual(next_path.name, "report_2.md")
            self.assertEqual(fs_utils.sanitize_stem("CON"), "document")

    def test_pdf_engine_converts_real_pdf_to_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "simple.md"
            completed = run_engine(ROOT / "test_documents" / "01_simple_text.pdf", destination)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            markdown = destination.read_text(encoding="utf-8")
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["characters"], len(markdown))
            self.assertGreater(len(markdown), CHARACTER_FLOOR)
            self.assertGreater(payload["pages"], 1)

    def test_pdf_engine_relinks_real_extracted_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "hybrid.md"
            completed = run_engine(ROOT / "test_documents" / "08_hybrid_pdf.pdf", destination)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertGreater(payload["image_count"], 0)
            images_directory = Path(payload["images_dir"])
            extracted = sorted(images_directory.glob("img_*.png"))
            self.assertEqual(len(extracted), payload["image_count"])
            markdown = destination.read_text(encoding="utf-8")
            for image in extracted:
                self.assertIn(f"{images_directory.name}/{image.name}", markdown)

    def test_pdf_engine_classifies_encrypted_pdf_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "encrypted.md"
            completed = run_engine(ROOT / "test_documents" / "09_encrypted_password.pdf", destination)
            self.assertEqual(completed.returncode, 3, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["status"], "encrypted")
            self.assertFalse(destination.exists())

    def test_pandoc_with_math_filter_preserves_math_code_and_currency(self) -> None:
        pandoc = tool_paths.resolve_tool("pandoc")["path"]
        self.assertIsNotNone(pandoc)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "probe.md"
            source.write_text(
                "Inline math $x^2 + y^2 = z^2$ and display math:\n\n"
                "$$\\int_0^\\infty e^{-t} \\, dt = 1$$\n\n"
                "Shell variables `$PATH` and `$HOME` are code spans.\n"
                "Currency: 100 USD and cash $5.00 must survive.\n\n"
                "``` math\nint_0^1 x dx\n```\n",
                encoding="utf-8",
            )
            output = directory / "probe.md"
            completed = subprocess.run(
                [pandoc, "--from=markdown+tex_math_dollars", "--to=gfm", f"--lua-filter={MATH_FILTER}", "--output", str(output), str(source)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            markdown = output.read_text(encoding="utf-8")
            self.assertIn("$x^2 + y^2 = z^2$", markdown)
            self.assertIn("$$", markdown)
            self.assertIn("`$PATH`", markdown)
            self.assertIn("`$HOME`", markdown)
            self.assertIn("\\$5.00", markdown)
            # User documentation fenced as math is not converted to display math.
            self.assertIn("``` math", markdown)
            self.assertEqual(markdown.count("``` math"), 1)

    def test_pandoc_converts_docx_and_txt_with_math_filter(self) -> None:
        pandoc = tool_paths.resolve_tool("pandoc")["path"]
        self.assertIsNotNone(pandoc)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            docx_output = directory / "fixture.md"
            docx = subprocess.run(
                [pandoc, "--from=docx", "--to=gfm", f"--lua-filter={MATH_FILTER}", "--output", str(docx_output), str(ROOT / "test_documents" / "10_docx_engine_fixture.docx")],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=30,
            )
            self.assertEqual(docx.returncode, 0, docx.stderr)
            self.assertGreater(len(docx_output.read_text(encoding="utf-8")), 100)

            text_output = directory / "plain.md"
            text = subprocess.run(
                [pandoc, "--from=markdown", "--to=gfm", f"--lua-filter={MATH_FILTER}", "--output", str(text_output), str(ROOT / "test_documents" / "11_plain_text_fixture.txt")],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=30,
            )
            self.assertEqual(text.returncode, 0, text.stderr)
            markdown = text_output.read_text(encoding="utf-8")
            self.assertIn("a^2 + b^2 = c^2", markdown)
            self.assertIn("\\int_0^\\infty e^{-t} dt = 1", markdown)
            self.assertIn("`$PATH`", markdown)
            self.assertIn("`$HOME`", markdown)


class BenchmarkDatasetTests(unittest.TestCase):
    """Statistical acceptance criteria for the regenerated fixture suite."""

    def test_text_fixtures_exceed_character_floors(self) -> None:
        for name in (
            "01_simple_text.pdf",
            "02_two_column_scientific_paper.pdf",
            "03_persian_rtl_document.pdf",
            "05_equation_heavy_math.pdf",
            "06_complex_tables.pdf",
            "07_mixed_script_document.pdf",
            "08_hybrid_pdf.pdf",
        ):
            with self.subTest(fixture=name):
                text = extracted_text(ROOT / "test_documents" / name)
                self.assertGreaterEqual(len(text.strip()), CHARACTER_FLOOR, name)

    def test_persian_fixture_contains_real_arabic_codepoints(self) -> None:
        text = extracted_text(ROOT / "test_documents" / "03_persian_rtl_document.pdf")
        persian = [character for character in text if 0x0600 <= ord(character) <= 0x06FF]
        self.assertGreaterEqual(len(persian), PERSIAN_CODEPOINT_FLOOR)

    def test_engine_output_preserves_persian_codepoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "persian.md"
            completed = run_engine(ROOT / "test_documents" / "03_persian_rtl_document.pdf", destination)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            markdown = destination.read_text(encoding="utf-8")
            persian = [character for character in markdown if 0x0600 <= ord(character) <= 0x06FF]
            self.assertGreaterEqual(len(persian), PERSIAN_CODEPOINT_FLOOR)

    def test_engine_succeeds_with_output_directory_containing_spaces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pdf2md space dir ") as temporary:
            destination = Path(temporary) / "hybrid report.md"
            completed = run_engine(ROOT / "test_documents" / "08_hybrid_pdf.pdf", destination)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertGreater(payload["image_count"], 0)
            markdown = destination.read_text(encoding="utf-8")
            for line in markdown.splitlines():
                if "![" in line:
                    self.assertNotIn("\\", line, "image links must use forward slashes")

    def test_scanned_pdf_is_converted_and_its_pages_extracted_as_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "scanned.md"
            completed = run_engine(ROOT / "test_documents" / "04_scanned_photo.pdf", destination)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertGreaterEqual(payload["pages"], 3)
            self.assertGreaterEqual(payload["image_count"], 3)
            markdown = destination.read_text(encoding="utf-8")
            self.assertIn("![image]", markdown)

    def test_multi_page_conversion_reports_real_page_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "paper.md"
            completed = run_engine(ROOT / "test_documents" / "02_two_column_scientific_paper.pdf", destination)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertGreater(payload["pages"], 3)

    def test_watchdog_timeout_is_a_structured_runtime_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "slow.md"
            completed = run_engine(
                ROOT / "test_documents" / "01_simple_text.pdf",
                destination,
                "--timeout",
                "0.05",
            )
            self.assertEqual(completed.returncode, 5, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "timeout")
            self.assertIn("timeout", payload["error"])
            self.assertFalse(destination.exists())

    def test_page_limit_returns_a_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "limited.md"
            completed = run_engine(
                ROOT / "test_documents" / "02_two_column_scientific_paper.pdf",
                destination,
                "--max-pages",
                "1",
            )
            self.assertEqual(completed.returncode, 4, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "failed")
            self.assertIn("exceeding", payload["error"])
            self.assertFalse(destination.exists())


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_has_isolated_test_cache_and_lockfile_keyed_release_cache(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8"))
        job = workflow["jobs"]["build-windows"]
        steps = job["steps"]
        rust_cache_steps = [step for step in steps if step.get("uses") == "Swatinem/rust-cache@v2"]
        self.assertEqual(len(rust_cache_steps), 2, "release and test caches must be separate")
        release, tests = rust_cache_steps
        self.assertEqual(release["with"]["shared-key"], "tauri-v2-windows-release-v2")
        self.assertIn("hashFiles('src-tauri/Cargo.lock')", release["with"]["key"])
        self.assertEqual(tests["with"]["shared-key"], "tauri-v2-windows-tests-v2")
        test_step = next(step for step in steps if step.get("name") == "Run native Rust tests")
        self.assertEqual(test_step["run"], "cargo test --manifest-path src-tauri/Cargo.toml --lib")


if __name__ == "__main__":
    unittest.main(verbosity=2)
