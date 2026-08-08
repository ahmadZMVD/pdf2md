"""Run the Phase 2 PDF dataset through the real subprocess conversion engine."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "scripts" / "pdf_engine.py"
DATASET = (
    "01_simple_text.pdf",
    "02_two_column_scientific_paper.pdf",
    "03_persian_rtl_document.pdf",
    "05_equation_heavy_math.pdf",
    "06_complex_tables.pdf",
    "08_hybrid_pdf.pdf",
)


def benchmark() -> list[dict[str, object]]:
    """Return real wall-clock measurements for each required PDF fixture."""

    measurements: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="pdf2md-phase2-") as temporary:
        output_directory = Path(temporary)
        for filename in DATASET:
            source = ROOT / "test_documents" / filename
            destination = output_directory / f"{source.stem}.md"
            started = time.perf_counter()
            completed = subprocess.run(
                [sys.executable, str(ENGINE), "--input", str(source), "--output", str(destination)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=90,
                check=False,
            )
            elapsed = round(time.perf_counter() - started, 3)
            result: dict[str, object] = {
                "source_file": filename,
                "status": "failed",
                "extracted_chars": 0,
                "elapsed_seconds": elapsed,
            }
            try:
                payload = json.loads(completed.stdout)
            except json.JSONDecodeError:
                payload = {}
            if completed.returncode == 0 and payload.get("status") == "success" and destination.is_file():
                result.update(
                    {
                        "status": "success",
                        "extracted_chars": len(destination.read_text(encoding="utf-8")),
                        "engine_elapsed_seconds": payload.get("elapsed_seconds"),
                    }
                )
            else:
                result["error"] = payload.get("error") or completed.stderr.strip() or "conversion failed"
            measurements.append(result)
    return measurements


if __name__ == "__main__":
    results = benchmark()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    raise SystemExit(0 if all(result["status"] == "success" for result in results) else 1)
