"""Execution-based Phase 2 tests for conversion engines and path contracts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fs_utils  # noqa: E402
import tool_paths  # noqa: E402


class Phase2ExecutionTests(unittest.TestCase):
    def run_engine(self, source: Path, destination: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "pdf_engine.py"), "--input", str(source), "--output", str(destination)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=45,
        )

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
            completed = self.run_engine(ROOT / "test_documents" / "01_simple_text.pdf", destination)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            markdown = destination.read_text(encoding="utf-8")
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["characters"], len(markdown))
            self.assertGreater(len(markdown), 100)
            self.assertGreater(payload["pages"], 0)

    def test_pdf_engine_relinks_real_extracted_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "hybrid.md"
            completed = self.run_engine(ROOT / "test_documents" / "08_hybrid_pdf.pdf", destination)
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
            completed = self.run_engine(ROOT / "test_documents" / "09_encrypted_password.pdf", destination)
            self.assertEqual(completed.returncode, 3, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["status"], "encrypted")
            self.assertFalse(destination.exists())

    def test_pandoc_converts_docx_and_preserves_txt_math_notation(self) -> None:
        pandoc = tool_paths.resolve_tool("pandoc")["path"]
        self.assertIsNotNone(pandoc)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            docx_output = directory / "fixture.md"
            docx = subprocess.run(
                [pandoc, "--from=docx", "--to=gfm", "--output", str(docx_output), str(ROOT / "test_documents" / "10_docx_engine_fixture.docx")],
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
                [pandoc, "--from=markdown", "--to=gfm", "--output", str(text_output), str(ROOT / "test_documents" / "11_plain_text_fixture.txt")],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=30,
            )
            self.assertEqual(text.returncode, 0, text.stderr)
            markdown = text_output.read_text(encoding="utf-8")
            # Pandoc emits valid GFM code representations for TeX; the native
            # queue's tested normalizer restores dollar delimiters afterwards.
            # This execution test ensures Pandoc itself did not strip either
            # formula body before that final native step.
            self.assertIn("a2 + b2 = c2", markdown)
            self.assertIn("\\int_0\\infty e{-t} dt = 1", markdown)


if __name__ == "__main__":
    unittest.main(verbosity=2)
