"""Run the required local checks before a Git push."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from env_check import run_command


ROOT = Path(__file__).resolve().parents[1]


def run_step(label: str, command: list[str], timeout_seconds: int = 180) -> None:
    print(f"[pre-push] {label}")
    result = run_command(command, timeout_seconds=timeout_seconds)
    output = result["stdout"] or result["stderr"]
    if output:
        print(output)
    if result["return_code"] != 0:
        raise SystemExit(f"[pre-push] {label} failed with exit code {result['return_code']}")


def main() -> int:
    audit_result = run_command([sys.executable, str(ROOT / "scripts" / "env_check.py")])
    if audit_result["return_code"] != 0:
        print(audit_result["stderr"], file=sys.stderr)
        return 1
    audit = json.loads(audit_result["stdout"])
    if audit.get("status") != "ok":
        print("[pre-push] required local environment audit is not healthy", file=sys.stderr)
        return 1
    print("[pre-push] environment audit passed")

    run_step(
        "Python/schema tests",
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
    )
    run_step("Frontend adapter tests", ["npm", "run", "test:frontend"])
    run_step("Frontend production build", ["npm", "run", "build"])
    print("[pre-push] all local checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
