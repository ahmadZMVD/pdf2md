"""Audit the lightweight local prerequisites used by the Phase 1 shell.

Rust, Cargo, and MSVC are deliberately represented as delegated checks. Native
compilation belongs to the GitHub Actions Windows runner for this project.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
COMMAND_TIMEOUT_SECONDS = 15


def run_command(command: Sequence[str]) -> dict[str, Any]:
    """Run a bounded probe and return machine-readable process details."""

    invocation = list(command)
    resolved = shutil.which(invocation[0])
    if resolved and Path(resolved).suffix.lower() in {".cmd", ".bat"}:
        invocation = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", resolved, *invocation[1:]]

    try:
        completed = subprocess.run(
            invocation,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "return_code": None,
            "stdout": "",
            "stderr": str(error),
            "timed_out": isinstance(error, subprocess.TimeoutExpired),
        }

    return {
        "return_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "timed_out": False,
    }


def first_line(value: str) -> str:
    return next((line.strip() for line in value.splitlines() if line.strip()), "")


def version_tuple(value: str) -> tuple[int, ...] | None:
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def check_command(
    name: str,
    command: Sequence[str],
    minimum: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    executable = shutil.which(command[0])
    result: dict[str, Any] = {
        "available": False,
        "path": executable,
        "version": "",
        "meets_minimum": minimum is None,
        "timed_out": False,
    }
    if executable is None:
        return result

    probe = run_command(command)
    raw_version = first_line(probe["stdout"] or probe["stderr"])
    detected = version_tuple(raw_version)
    result.update(
        {
            "available": probe["return_code"] == 0,
            "version": raw_version,
            "detected_version": list(detected) if detected else None,
            "meets_minimum": minimum is None or (detected is not None and detected >= minimum),
            "timed_out": probe["timed_out"],
        }
    )
    return result


def check_python() -> dict[str, Any]:
    executable = shutil.which("python") or sys.executable
    result: dict[str, Any] = {
        "available": False,
        "path": executable,
        "version": "",
        "detected_version": None,
        "meets_minimum": False,
        "pymupdf4llm_installed": False,
        "pymupdf4llm_version": "",
        "pymupdf4llm_error": "",
        "timed_out": False,
    }
    if not executable:
        return result

    version_probe = run_command([executable, "--version"])
    raw_version = first_line(version_probe["stdout"] or version_probe["stderr"])
    detected = version_tuple(raw_version)
    package_probe = run_command(
        [
            executable,
            "-c",
            "import pymupdf4llm; print(getattr(pymupdf4llm, '__version__', 'installed'))",
        ]
    )
    package_version = first_line(package_probe["stdout"] or package_probe["stderr"])
    result.update(
        {
            "available": version_probe["return_code"] == 0,
            "version": raw_version,
            "detected_version": list(detected) if detected else None,
            "meets_minimum": detected is not None and detected >= (3, 11),
            "pymupdf4llm_installed": package_probe["return_code"] == 0,
            "pymupdf4llm_version": package_version if package_probe["return_code"] == 0 else "",
            "pymupdf4llm_error": "" if package_probe["return_code"] == 0 else package_version,
            "timed_out": version_probe["timed_out"] or package_probe["timed_out"],
        }
    )
    return result


def delegated_tool(name: str) -> dict[str, Any]:
    return {
        "available": None,
        "status": "delegated_to_github_actions",
        "checked_locally": False,
        "reason": f"{name} is intentionally not probed on the local machine",
    }


def audit() -> dict[str, Any]:
    python = check_python()
    tools = {
        "node": check_command("node", ["node", "--version"], (18, 0)),
        "npm": check_command("npm", ["npm", "--version"], (9, 0)),
        "python": python,
        "pandoc": check_command("pandoc", ["pandoc", "-v"]),
        "git": check_command("git", ["git", "--version"]),
        "gh": check_command("gh", ["gh", "--version"]),
        "rustc": delegated_tool("rustc"),
        "cargo": delegated_tool("cargo"),
        "msvc": delegated_tool("MSVC"),
    }
    required = ["node", "npm", "python", "pandoc", "git", "gh"]
    required_ready = all(
        tools[name]["available"] and tools[name]["meets_minimum"] for name in required
    ) and python["pymupdf4llm_installed"]
    return {
        "schema_version": 1,
        "status": "ok" if required_ready else "degraded",
        "required_tools_available": required_ready,
        "platform": {
            "system": platform.system().lower(),
            "release": platform.release(),
            "python_executable": sys.executable,
        },
        "tools": tools,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, sort_keys=True))
