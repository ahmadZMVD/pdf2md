"""Execution and schema tests for Phase 1 infrastructure."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class Phase1Tests(unittest.TestCase):
    def test_environment_audit_executes_and_matches_schema(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "env_check.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["schema_version"], 1)
        self.assertIn(payload["status"], {"ok", "degraded"})
        self.assertIsInstance(payload["required_tools_available"], bool)
        for tool_name in ("node", "npm", "python", "pandoc", "git", "gh"):
            tool = payload["tools"][tool_name]
            self.assertIsInstance(tool["available"], bool)
            self.assertIsInstance(tool["version"], str)
            self.assertIsInstance(tool["meets_minimum"], bool)

        for delegated_name in ("rustc", "cargo", "msvc"):
            delegated = payload["tools"][delegated_name]
            self.assertEqual(delegated["status"], "delegated_to_github_actions")
            self.assertFalse(delegated["checked_locally"])

    def test_tauri_window_configuration_and_scaffold(self) -> None:
        configuration = json.loads(
            (ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
        )
        window = configuration["app"]["windows"][0]
        self.assertEqual(window["width"], 380)
        self.assertEqual(window["height"], 520)
        self.assertEqual(window["title"], "PDF & Document Converter")
        self.assertFalse(window["resizable"])
        self.assertFalse(window["fullscreen"])
        self.assertTrue(window["decorations"])
        self.assertEqual(window["theme"], "Dark")
        self.assertEqual(window["label"], "main")
        self.assertTrue(configuration["app"]["withGlobalTauri"])
        for relative_path in (
            "src/index.html",
            "src/main.js",
            "src/styles/tailwind.css",
            "src-tauri/icons/icon.ico",
            "src-tauri/src/main.rs",
            "src-tauri/src/lib.rs",
            "src-tauri/src/commands/health.rs",
            "src-tauri/Cargo.toml",
        ):
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)

        icon_header = (ROOT / "src-tauri" / "icons" / "icon.ico").read_bytes()
        self.assertEqual(icon_header[:4], b"\x00\x00\x01\x00")
        self.assertEqual(int.from_bytes(icon_header[4:6], "little"), 1)

    def test_workflow_yaml_is_structurally_valid(self) -> None:
        workflow = yaml.safe_load(
            (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
        )
        self.assertIsInstance(workflow, dict)
        self.assertEqual(workflow["name"], "Windows desktop build")
        self.assertIn("push", workflow["on"])
        self.assertIn("main", workflow["on"]["push"]["branches"])
        job = workflow["jobs"]["build-windows"]
        self.assertEqual(job["runs-on"], "windows-latest")
        step_uses = [step.get("uses") for step in job["steps"] if isinstance(step, dict)]
        self.assertIn("actions/checkout@v4", step_uses)
        self.assertIn("actions/setup-node@v4", step_uses)
        self.assertIn("dtolnay/rust-toolchain@stable", step_uses)
        self.assertIn("actions/upload-artifact@v4", step_uses)
        rust_test_steps = [
            step.get("run")
            for step in job["steps"]
            if isinstance(step, dict) and step.get("name") == "Run native Rust tests"
        ]
        self.assertEqual(
            rust_test_steps,
            ["cargo test --manifest-path src-tauri/Cargo.toml --lib --release"],
        )
        upload_step = next(
            step for step in job["steps"] if step.get("uses") == "actions/upload-artifact@v4"
        )
        self.assertEqual(upload_step["with"]["name"], "PDF-Converter-Windows-EXE")
        self.assertEqual(upload_step["with"]["if-no-files-found"], "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
