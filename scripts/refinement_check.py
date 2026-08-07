"""Run five independent executable checks for Phase 1.5 refinement work."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Callable

import yaml


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    invocation = list(command)
    executable = shutil.which(invocation[0])
    if executable and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        invocation = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", executable, *invocation[1:]]
    return subprocess.run(
        invocation,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_workflow_contract() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8"))
    require(isinstance(workflow, dict), "workflow must decode to a mapping")
    triggers = workflow["on"]
    require(triggers["push"]["branches"] == ["main"], "push must target main")
    require("v*" in triggers["push"]["tags"], "version tags must trigger the workflow")
    require(triggers["pull_request"]["branches"] == ["main"], "pull requests must target main")
    require("workflow_dispatch" in triggers, "manual dispatch must remain available")

    quality = workflow["jobs"]["quality"]
    build = workflow["jobs"]["build-windows"]
    require(quality["runs-on"] == "ubuntu-latest", "quality job must use the lightweight runner")
    require(build["runs-on"] == "windows-latest", "native job must use the Windows runner")
    require(build["needs"] == "quality", "native build must be gated by quality")
    require(workflow["permissions"]["contents"] == "read", "workflow default permission must be read-only")
    release = workflow["jobs"]["release"]
    require(release["needs"] == "build-windows", "release must consume the verified build")
    require(release["permissions"]["contents"] == "write", "release job needs scoped write permission")
    require(release["if"] == "startsWith(github.ref, 'refs/tags/v')", "release job must be tag-only")

    quality_checkout = next(step for step in quality["steps"] if step.get("uses") == "actions/checkout@v4")
    require(quality_checkout["with"]["fetch-depth"] == 0, "CI commit validation needs complete history")
    semantic_step = next(step for step in quality["steps"] if step.get("name") == "Validate semantic commit subjects")
    require(semantic_step["run"] == "python scripts/validate_commit.py --ci", "CI must run range validation")
    semantic_env = semantic_step["env"]
    require("github.event.pull_request.base.sha" in semantic_env["CI_BASE_SHA"], "PR base SHA must be used for commit validation")
    require("github.event.pull_request.head.sha" in semantic_env["CI_HEAD_SHA"], "PR head SHA must be used for commit validation")
    require("github.sha" in semantic_env["CI_HEAD_SHA"], "push commit SHA must be used for commit validation")

    build_steps = build["steps"]
    lock_index = next(i for i, step in enumerate(build_steps) if step.get("name") == "Generate deterministic Cargo.lock")
    cache_index = next(i for i, step in enumerate(build_steps) if step.get("uses") == "Swatinem/rust-cache@v2")
    require(lock_index < cache_index, "Cargo.lock must exist before cache key evaluation")
    cache_step = build_steps[cache_index]
    require(cache_step["with"]["workspaces"] == "src-tauri -> target", "Tauri target directory must be cached")
    require(cache_step["with"]["shared-key"] == "tauri-v2-windows-release-v2", "cache namespace must be stable")
    require(cache_step["with"]["cache-on-failure"] is False, "failed native runs must not poison the exact cache key")
    require(cache_step["id"] == "rust-cache", "cache result must be addressable")
    require(any(step.get("name") == "Report Rust cache result" for step in build_steps), "cache result must be reported")

    release_steps = release["steps"]
    download_step = next(step for step in release_steps if step.get("uses") == "actions/download-artifact@v4")
    require(download_step["with"]["name"] == "PDF-Converter-Windows-EXE", "release must use the verified artifact")
    release_step = next(step for step in release_steps if step.get("uses") == "softprops/action-gh-release@v2")
    require("*.exe" in release_step["with"]["files"], "release must attach the Windows executable")
    require(not any("create_icon.py" in json.dumps(step) for step in build_steps), "CI must use the committed icon")

    cargo = tomllib.loads((ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))
    release_profile = cargo["profile"]["release"]
    require(release_profile["lto"] == "thin", "release builds must use CI-efficient ThinLTO")
    require(release_profile["codegen-units"] == 16, "release code generation must remain parallel")
    require(release_profile["panic"] == "abort", "release panic handling changed")
    require(release_profile["strip"] is True, "release binaries must remain stripped")


def test_pre_push_gate_executes() -> None:
    completed = run([sys.executable, "scripts/pre_push_check.py"], timeout=240)
    require(completed.returncode == 0, completed.stdout + completed.stderr)
    require("all local checks passed" in completed.stdout, "pre-push gate did not report completion")


def test_semantic_validator_and_hook() -> None:
    validator = ROOT / "scripts" / "validate_commit.py"
    hook_config = run(["git", "config", "--local", "--get", "core.hooksPath"])
    require(hook_config.returncode == 0 and hook_config.stdout.strip() == ".githooks", "local hooks are not configured")

    with tempfile.TemporaryDirectory(prefix="pdf2md-semantic-") as directory:
        message = Path(directory) / "commit-message.txt"
        for subject in ("feat: add contract", "fix: handle absence", "docs: explain gate", "perf: reduce work", "refactor: isolate adapter"):
            message.write_text(subject + "\n", encoding="utf-8")
            accepted = run([sys.executable, str(validator), str(message)])
            require(accepted.returncode == 0, f"accepted subject rejected: {subject}")

        message.write_text("chore: unsupported prefix\n", encoding="utf-8")
        rejected = run([sys.executable, str(validator), str(message)])
        require(rejected.returncode != 0, "unsupported semantic prefix was accepted")

        message.write_text("feat: hook execution\n", encoding="utf-8")
        hook_accepted = run(["git", "hook", "run", "commit-msg", "--", str(message)])
        require(hook_accepted.returncode == 0, hook_accepted.stdout + hook_accepted.stderr)
        message.write_text("chore: hook rejection\n", encoding="utf-8")
        hook_rejected = run(["git", "hook", "run", "commit-msg", "--", str(message)])
        require(hook_rejected.returncode != 0, "commit-msg hook accepted an invalid subject")


def test_ipc_adapter_executes() -> None:
    completed = run(["npm", "run", "test:frontend"], timeout=60)
    require(completed.returncode == 0, completed.stdout + completed.stderr)
    require("IPC adapter tests passed" in completed.stdout, "frontend adapter test did not execute its contract")


def markdown_headings(path: Path) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(r"^#{1,3} +(.+?)\s*$", path.read_text(encoding="utf-8"), re.MULTILINE)]


def test_portfolio_documents() -> None:
    required = (
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
        ".github/pull_request_template.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "docs/PORTABLE_PACKAGING_STRATEGY.md",
    )
    for relative_path in required:
        path = ROOT / relative_path
        require(path.is_file() and path.stat().st_size > 0, f"missing portfolio document: {relative_path}")

    for relative_path in (required[0], required[1]):
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        require(content.startswith("---\n"), f"issue template lacks front matter: {relative_path}")
        front_matter = content.split("\n---\n", 1)[0].removeprefix("---\n")
        metadata = yaml.safe_load(front_matter)
        require(isinstance(metadata, dict), f"issue metadata is not structured: {relative_path}")
        require(isinstance(metadata.get("name"), str) and metadata["name"], f"issue name missing: {relative_path}")
        require(isinstance(metadata.get("about"), str) and metadata["about"], f"issue description missing: {relative_path}")

    pr_headings = markdown_headings(ROOT / ".github" / "pull_request_template.md")
    require(pr_headings[:3] == ["Summary", "Verification", "Risk and rollback"], "PR template section order changed")
    require("## Checklist" in (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8"), "PR checklist missing")

    changelog_headings = markdown_headings(ROOT / "CHANGELOG.md")
    require(changelog_headings[:2] == ["Changelog", "[Unreleased]"], "changelog structure is incomplete")

    roadmap_path = ROOT / "docs" / "PORTABLE_PACKAGING_STRATEGY.md"
    roadmap = roadmap_path.read_text(encoding="utf-8")
    require(roadmap.startswith("---\n"), "portable roadmap lacks machine-readable metadata")
    roadmap_front_matter = roadmap.split("\n---\n", 1)[0].removeprefix("---\n")
    roadmap_metadata = yaml.safe_load(roadmap_front_matter)
    require(isinstance(roadmap_metadata, dict), "portable roadmap metadata is not structured")
    require(roadmap_metadata["schema_version"] == 1, "portable roadmap schema is unsupported")
    require(roadmap_metadata["phase"] == 1.5, "portable roadmap belongs to the wrong phase")
    require(roadmap_metadata["implementation_status"] == "roadmap_only", "Phase 2 work leaked into the roadmap phase")
    require(roadmap_metadata["installer"] == "nsis", "portable installer target changed")
    require(roadmap_metadata["max_installed_payload_mb"] == 120, "installed payload budget changed")
    require(
        roadmap_metadata["runtime_components"] == ["python-embedded", "pymupdf4llm", "pandoc"],
        "portable runtime component contract changed",
    )

    roadmap_headings = markdown_headings(roadmap_path)
    require(roadmap_headings[:2] == ["Portable Packaging Strategy", "Objective"], "portable roadmap headings are incomplete")

    icon = (ROOT / "src-tauri" / "icons" / "icon.ico").read_bytes()
    require(len(icon) >= 22, "static icon is too small to contain an ICO directory entry")
    require(icon[:6] == b"\x00\x00\x01\x00\x01\x00", "static icon header is invalid")
    image_size = int.from_bytes(icon[14:18], "little")
    image_offset = int.from_bytes(icon[18:22], "little")
    require(image_size > 0 and image_offset >= 22, "static icon directory entry is invalid")
    require(image_offset + image_size <= len(icon), "static icon image exceeds the committed file")


TESTS: tuple[tuple[str, Callable[[], None]], ...] = (
    ("workflow_contract", test_workflow_contract),
    ("pre_push_gate_executes", test_pre_push_gate_executes),
    ("semantic_validator_and_hook", test_semantic_validator_and_hook),
    ("ipc_adapter_executes", test_ipc_adapter_executes),
    ("portfolio_documents", test_portfolio_documents),
)


def main() -> int:
    results: list[dict[str, object]] = []
    for name, test in TESTS:
        started = time.perf_counter()
        try:
            test()
        except Exception as error:  # noqa: BLE001 - report every independent check
            results.append({"name": name, "status": "failed", "duration_seconds": round(time.perf_counter() - started, 3), "error": str(error)})
            print(json.dumps({"tests": results}, indent=2), file=sys.stderr)
            return 1
        results.append({"name": name, "status": "passed", "duration_seconds": round(time.perf_counter() - started, 3)})
        print(f"[refinement] {name}: passed ({results[-1]['duration_seconds']} s)")

    print(json.dumps({"total": len(results), "passed": len(results), "failed": 0, "tests": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
