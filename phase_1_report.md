# Phase 1 Report — Cloud-First Tauri Shell

Status: **completed**

Phase 1 is locally verified and passed the cloud delivery gate. The implementation is pushed to `main` at `474c5de3c397ee5c46c2edf923d46bc91055a56f`.

## Measurements

| Area | Result |
|---|---|
| Local prerequisites | Node 26.1.0, npm 11.16.0, Python 3.11.9, PyMuPDF4LLM 1.28.0, Pandoc 3.10, Git 2.54.0, GitHub CLI 2.92.0 |
| Local Python tests | 3 passed, 0 failed |
| Frontend production build | Passed in 2.9 seconds |
| Cloud Rust tests | 2 passed, 0 failed |
| Cloud run | [31127656822](https://github.com/ahmadZMVD/pdf2md/actions/runs/31127656822), success, 535 seconds |
| Windows artifact | `PDF-Converter-Windows-EXE`, verified `.exe`, 1,299,496 bytes (1.299496 MB) |

## Delivered architecture

- Tauri v2 shell with a fixed 380×520 dark window.
- Static HTML/Tailwind frontend with a minimal healthcheck view and completion mark.
- Rust `check_system_health` IPC command with fresh subprocess probes and bounded timeouts.
- Tray “Show window” and “Quit” lifecycle; close requests hide the window.
- GitHub Actions `windows-latest` workflow that installs Node/Rust, runs Rust tests, builds the NSIS installer, verifies the executable, and uploads it.
- Standard-library-generated Windows application icon required by Tauri resource packaging.

## Test and reporting integrity

The three local tests execute `scripts/env_check.py`, parse the Tauri JSON configuration, validate the workflow through PyYAML, and validate the ICO header. The two cloud tests execute real Rust subprocess/probe helper behavior. Coverage was not instrumented, so the JSON report uses `null` rather than an invented percentage.

## Limitations

Document conversion engines are intentionally deferred to Phase 2. The successful GitHub run was dispatched explicitly because the initial push event did not materialize a run; the exact event and commit are recorded in `phase_1_report.json`. Local native compilation and interactive native UI execution remain cloud-delegated by policy.
