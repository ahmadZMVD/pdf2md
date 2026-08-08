"""Dynamic resolution of the Python and Pandoc executables.

Resolution order (shared contract with the Rust core in
``src-tauri/src/commands/tools.rs``):

1. Portable binaries bundled next to the application in ``resources/bin/``.
2. The first working candidate on the system ``PATH`` environment variable.

The resolver never raises for a missing tool: callers receive
``status == "unavailable"`` and degrade gracefully, so the conversion queue
never crashes on machines without installed tools.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RESOURCE_DIRS = (
    SCRIPT_DIR.parent / "resources" / "bin",
    SCRIPT_DIR / "resources" / "bin",
    Path.cwd() / "resources" / "bin",
)

TOOL_CANDIDATES = {
    "python": ("python", "python3", "py"),
    "pandoc": ("pandoc",),
}


def candidate_names(tool):
    """Executable basenames probed for *tool*, in priority order."""
    return TOOL_CANDIDATES.get(tool, (tool,))


def bundled_file_names(tool):
    """File names checked inside ``resources/bin/`` for *tool*."""
    names = []
    for base in candidate_names(tool):
        names.append(base)
        if os.name == "nt":
            names.append(base + ".exe")
    seen = set()
    unique = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return tuple(unique)



def resolve_bundled(tool):
    """Return a bundled executable path inside ``resources/bin/`` or ``None``."""
    for directory in RESOURCE_DIRS:
        try:
            present = directory.is_dir()
        except OSError:
            continue
        if not present:
            continue
        for name in bundled_file_names(tool):
            candidate = directory / name
            try:
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate)
            except OSError:
                continue
    return None


def resolve_from_path(tool):
    """Return the first ``PATH`` executable for *tool*, or ``None``."""
    for name in candidate_names(tool):
        found = shutil.which(name)
        if found:
            return found
    return None


def resolve_tool(tool):
    """Resolve *tool* to a dict ``{"status", "path", "source"}``.

    ``status`` is one of ``bundled``, ``path``, or ``unavailable``. The
    function never raises for a missing tool; absence is reported so that
    callers (Rust queue worker, health probes, tests) can skip or degrade
    instead of crashing.
    """
    bundled = resolve_bundled(tool)
    if bundled:
        return {"status": "bundled", "path": bundled, "source": "resources_bin"}
    from_path = resolve_from_path(tool)
    if from_path:
        return {"status": "path", "path": from_path, "source": "system_path"}
    return {"status": "unavailable", "path": None, "source": None}


def python_argv():
    """argv prefix used to launch the Python conversion engine."""
    resolution = resolve_tool("python")
    if resolution["path"]:
        return [resolution["path"], "-X", "utf8", "-I"]
    # ``sys.executable`` is a deliberate final fallback for the Python engine
    # itself.  It keeps a packaged launcher functional if PATH lookup was
    # altered after the process started, while callers still receive an
    # explicit unavailable result for arbitrary missing executables.
    return [sys.executable, "-X", "utf8", "-I"]


if __name__ == "__main__":
    import json

    report = {tool: resolve_tool(tool) for tool in sorted(TOOL_CANDIDATES)}
    print(json.dumps(report, indent=2, ensure_ascii=False))
