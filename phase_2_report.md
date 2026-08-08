# Phase 2 Report — Conversion Engine, Sequential Queue Worker & Benchmark Validation

**Phase:** 2 — Processing Backend, Sequential Queue Worker, Engine Bridge & Benchmark Validation
**Status:** completed
**Verification:** conversion_engine_and_sequential_queue_verified
**Timestamp:** 2026-08-08T05:39:04Z
**Repository:** [ahmadZMVD/pdf2md](https://github.com/ahmadZMVD/pdf2md) — branch `main` — engine commit `94e9c23`

---

## 1. Local Environment Status

| Tool | Version | Availability |
| --- | --- | --- |
| Node.js | v26.1.0 | available |
| npm | 11.16.0 | available |
| System Python | 3.11.9 | available |
| PyMuPDF4LLM | 1.28.0 | available |
| Pandoc CLI | 3.10 | available |
| Git CLI | 2.54.0.windows.1 | available |
| GitHub CLI | 2.92.0 | available |
| rustc / cargo / MSVC | — | delegated to GitHub Actions (cloud-only by policy) |

## 2. Cloud Build Status

| Field | Value |
| --- | --- |
| Run ID | [31232120771](https://github.com/ahmadZMVD/pdf2md/actions/runs/31232120771) |
| Conclusion | `success` |
| Duration | 240 s (created 01:13:07Z → completed 01:17:07Z) |
| Jobs | quality: success (58 s) · build-windows: success (234 s) · release: skipped (no tag) |
| Artifact | `PDF-Converter-Windows-EXE` (1,774,935 bytes metadata) |
| Executable | `PDF & Document Converter_0.1.0_x64-setup.exe` — 1,803,421 bytes (1.80 MB) |

## 3. Unit Test Results

| Suite | Total | Passed | Failed | Measured |
| --- | ---: | ---: | ---: | --- |
| Local Python (`python -m unittest discover -s tests`) | 10 | 10 | 0 | 7.024 s |
| CI quality job Python (ubuntu runner) | 10 | 10 | 0 | 6.204 s |
| Local frontend IPC adapter (`npm run test:frontend`) | 24 assertions | 24 | 0 | — |
| Cloud Rust tests (`cargo test --lib --release`, windows-latest) | 9 | 9 | 0 | — |

All 5 verification areas (path resolution, engines, queue, IPC contract, dataset) passed on the first execution cycle.

## 4. Dataset Validation Benchmarks (real subprocess execution)

| Source file | Status | Extracted chars | Wall-clock s | Engine s |
| --- | --- | ---: | ---: | --- |
| 01_simple_text.pdf | success | 306 | 1.555 | 1.377 |
| 02_two_column_scientific_paper.pdf | success | 559 | 1.473 | 1.304 |
| 03_persian_rtl_document.pdf | success | 85 | 1.378 | 1.209 |
| 05_equation_heavy_math.pdf | success | 197 | 1.395 | 1.205 |
| 06_complex_tables.pdf | success | 130 | 1.532 | 1.362 |
| 08_hybrid_pdf.pdf | success | 223 | 1.420 | 1.256 |

All 6 required PDF fixtures converted successfully through `scripts/pdf_engine.py` with PyMuPDF4LLM. Image extraction and relative relinking (`_images/img_N.png`) were verified on the hybrid fixture. Encrypted PDF (`09_encrypted_password.pdf`) correctly returns exit code 3 with `status: "encrypted"` and writes no output; DOCX/TXT conversion via Pandoc retains TeX notation (verified by execution tests).

## 5. Pipeline Capabilities Delivered

- Dynamic tool path resolver (bundled `resources/bin/` → PATH fallback, graceful `unavailable`), mirrored in Rust (`commands/tools.rs`) and Python (`scripts/tool_paths.py`).
- Sequential queue worker in Rust: one subprocess at a time, deterministic memory, terminal-error recording, cancel semantics, per-item status (`queued/processing/completed/failed/unsupported/cancelled`).
- PyMuPDF4LLM PDF → GFM with `[filename]_images/` extraction and relative links.
- Pandoc DOCX/TXT → GFM with math-notation preservation.
- Incremental filenames (`report_1.md`, `report_2.md`) with batch-collision protection and Windows-safe stem sanitization.
- IPC contract parity: `start_conversion_batch`, `cancel_batch`, `get_queue_status` in Rust and browser-mock adapter without `window.__TAURI__` exceptions.

## 6. Git Delivery Gate

- Committed and pushed to `main` on GitHub: true.
- GitHub Actions workflow completed with `SUCCESS` (run 31232120771, full verification incl. native Rust tests): true.
- Native `.exe` installer generated, downloaded, and verified (size 1,803,421 bytes): true.

## 7. Self-Critique & Identified Limitations

Strengths: engines execute real subprocesses; no string-matching test stubs; error classification is structured (exit codes + JSON); queue holds no locks during I/O; memory released per item by dropping buffers.

Limitations:
- Fixtures are small (85–559 extracted chars); large real-world PDFs still need a stress pass.
- Pandoc math restoration is a deterministic heuristic, not a full TeX parser.
- PDF images are emitted only as PNG.
- Cancel waits for the in-flight subprocess to finish (deliberate, to avoid orphaned files).
- Cloud build 240 s — above the 3-minute aspiration; reported as measured.
