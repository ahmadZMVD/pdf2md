# Phase 2.1 remediation summary

Validated commit: `c3c6296`  
Cloud build: [run 31282097415](https://github.com/ahmadZMVD/pdf2md/actions/runs/31282097415) — success in 485 seconds

All documented remediation areas are verified. Cancellation now signals and kills the active child without waiting in the IPC command; the sequential worker reaps it. Child logs are disk-backed and capped at 64 KiB on read. Pandoc writes to a same-directory temporary file and publishes only on success.

The PDF engine now owns both its ordinary staging directory and PyMuPDF4LLM's sanitized path twin. It accepts images only from those paths, canonicalizes image links to forward-slash Markdown paths, removes both staging locations, and atomically publishes Markdown. The expanded suite embeds Arabic-script font data and verifies 4,184 Arabic-range codepoints in the Persian fixture.

Local execution checks passed: fixture generation, 23 Python tests, frontend IPC tests, six real PDF benchmarks, and production frontend build. The Windows cloud job passed 15 Rust tests and produced `PDF & Document Converter_0.1.0_x64-setup.exe` (1,825,695 bytes; valid `MZ` header).

Known limit: scanned PDFs are validated as image-preserving inputs; OCR text extraction is not part of the configured PyMuPDF4LLM/Pandoc stack.
