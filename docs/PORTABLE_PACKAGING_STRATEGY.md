---
schema_version: 1
phase: 1.5
implementation_status: roadmap_only
installer: nsis
max_installed_payload_mb: 120
runtime_components:
  - python-embedded
  - pymupdf4llm
  - pandoc
---

# Portable Packaging Strategy

## Objective

Produce one Windows NSIS installer that runs without a separately installed
Python, PyMuPDF4LLM, or Pandoc and remains below 120 MB. The installer is a
delivery target for the conversion phase; Phase 1.5 establishes the architecture
and CI boundary without enabling document conversion yet.

## Runtime layout

```text
PDF & Document Converter/
├── pdf2md.exe                 # Tauri native shell
├── runtime/python/python.exe  # Python Embedded distribution
├── runtime/python/Lib/...     # PyMuPDF4LLM and locked dependencies
├── runtime/pandoc/pandoc.exe  # pinned Pandoc CLI binary
└── resources/                 # versioned conversion profiles and metadata
```

The Rust command layer will resolve these paths relative to the application
resource directory, not from the user's global `PATH`. A development fallback
may probe system executables, but a packaged build must prefer its bundled
runtime and return structured diagnostics when a bundle component is corrupt or
missing.

## Build pipeline

1. Pin the Python Embedded ZIP release and verify its SHA-256 checksum.
2. Install only the required Python wheels into the embedded `Lib/site-packages`
   tree; run PyMuPDF4LLM import and representative conversion smoke tests.
3. Download a pinned Pandoc Windows binary and verify its checksum.
4. Compress resources where NSIS compression improves size without increasing
   startup cost materially.
5. Generate a manifest containing component versions, checksums, and license
   notices.
6. Build the NSIS installer on `windows-latest`, scan the final payload, and
   fail the job if the uncompressed runtime budget exceeds 120 MB.
7. Install into a clean Windows runner, execute a PDF/DOCX/TXT smoke matrix,
   and upload the installer only after the matrix passes.

## Size and performance budget

The 120 MB limit applies to the installed portable payload, not only the
compressed download. CI should report both values. Avoid bundling unused Python
packages, duplicate WebView assets, debug symbols, or a second Pandoc copy.
Startup should launch the shell first and initialize the conversion runtime
lazily so the idle UI remains responsive.

## Reliability and updates

Bundled component versions are updated as a single tested release unit. The
manifest makes rollback and incident triage deterministic. Security updates
must rebuild the full installer and repeat checksum, clean-install, and smoke
tests; the app must never silently fall back to an untrusted downloaded binary.

## Phase ownership

Phase 1.5 documents this strategy and leaves implementation disabled. Phase 2
will define the conversion service interface. A later packaging phase will add
embedded-runtime staging scripts, license files, checksums, the size gate, and
clean-runner smoke tests.
