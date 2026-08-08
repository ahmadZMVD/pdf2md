"""Filesystem helpers shared by the Python engines and validation scripts.

These are pure, unit-tested helpers. The Rust queue worker implements the
same incremental-naming contract (name.ext becomes name_1.ext then name_2.ext)
and both implementations are covered by tests so the contract cannot drift.
"""

from __future__ import annotations

from pathlib import Path

_WINDOWS_RESERVED = set()
_WINDOWS_RESERVED.update(("CON", "PRN", "AUX", "NUL"))
_WINDOWS_RESERVED.update("COM" + str(i) for i in range(1, 10))
_WINDOWS_RESERVED.update("LPT" + str(i) for i in range(1, 10))

_FORBIDDEN_CODES = list(range(32)) + [60, 62, 58, 124, 63, 42, 34, 47, 92]
_FORBIDDEN_CHARS = set(chr(code) for code in _FORBIDDEN_CODES)


def sanitize_stem(name):
    """Return *name* with characters unsafe in file names removed."""
    cleaned = "".join(ch for ch in name if ch not in _FORBIDDEN_CHARS).strip(" .")
    if not cleaned or cleaned.upper() in _WINDOWS_RESERVED:
        return "document"
    return cleaned


def incremental_output_path(directory, stem, suffix, taken=None):
    """Compute a collision-free output path inside *directory*.

    If report.md already exists, report_1.md is returned; if that also
    exists, report_2.md, and so on. *taken* optionally extends the
    collision set with names already reserved for earlier items of the
    same batch.
    """
    directory = Path(directory)
    taken = set(str(item).lower() for item in (taken or set()))
    candidate = directory / (stem + suffix)
    counter = 1
    while str(candidate).lower() in taken or candidate.exists():
        candidate = directory / (stem + "_" + str(counter) + suffix)
        counter += 1
    return candidate
