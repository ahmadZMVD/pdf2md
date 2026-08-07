"""Validate the repository's supported semantic commit subject prefixes."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


COMMIT_PATTERN = re.compile(r"^(feat|fix|docs|perf|refactor):\s+\S.*$")


def subject_from_file(path: str) -> str:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return lines[0].strip() if lines else ""


def commit_subject() -> str:
    message_file = os.environ.get("COMMIT_MSG_FILE", "")
    if len(sys.argv) > 1 and sys.argv[1] != "--ci":
        message_file = sys.argv[1]
    if message_file:
        return subject_from_file(message_file)
    pull_request_title = os.environ.get("PR_TITLE", "").strip()
    if pull_request_title:
        return pull_request_title
    completed = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip()


def git_subjects(revision: str) -> list[str]:
    completed = subprocess.run(
        ["git", "log", "--format=%s", "--no-merges", revision],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"cannot inspect revision {revision!r}")
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def ci_revision() -> str:
    event = os.environ.get("GITHUB_EVENT_NAME", "").strip()
    head = os.environ.get("CI_HEAD_SHA", "").strip() or "HEAD"

    if event == "pull_request":
        base = os.environ.get("CI_BASE_SHA", "").strip()
        return f"{base}..{head}" if base else f"{head}^!"

    if event == "push":
        before = os.environ.get("CI_BASE_SHA", "").strip()
        if before and not set(before) <= {"0"}:
            return f"{before}..{head}"

    return f"{head}^!"


def validate_ci() -> int:
    subjects: list[tuple[str, str]] = []
    pull_request_title = os.environ.get("PR_TITLE", "").strip()
    if pull_request_title:
        subjects.append(("pull request title", pull_request_title))

    try:
        revision = ci_revision()
        commit_subjects = git_subjects(revision)
    except RuntimeError as error:
        print(f"Semantic validation could not inspect CI commits: {error}", file=sys.stderr)
        return 1

    subjects.extend(("commit subject", subject) for subject in commit_subjects)
    if not subjects:
        print("Semantic validation found no commit subject to inspect.", file=sys.stderr)
        return 1

    invalid = [(kind, subject) for kind, subject in subjects if not COMMIT_PATTERN.fullmatch(subject)]
    if invalid:
        for kind, subject in invalid:
            print(f"Invalid {kind}: {subject!r}", file=sys.stderr)
        return 1

    print(f"Semantic validation accepted {len(subjects)} subject(s).")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--ci":
        return validate_ci()

    subject = commit_subject()
    if not COMMIT_PATTERN.fullmatch(subject):
        print(
            "Commit subject must begin with feat:, fix:, docs:, perf:, or refactor: "
            f"and contain a non-empty description. Received: {subject!r}",
            file=sys.stderr,
        )
        return 1
    print(f"Semantic commit subject accepted: {subject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
