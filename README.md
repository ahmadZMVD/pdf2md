# PDF & Document Converter

The desktop app has a fixed-size Tauri v2 shell, browser-safe IPC adapter, and
cloud-only Windows build and release gate. Phase 2 adds a single-worker
conversion queue: PDF files are converted by PyMuPDF4LLM through the system
Python runtime, while DOCX and TXT files are converted to GFM with Pandoc.

The worker processes one document at a time, creates collision-free output
names, extracts PDF images into adjacent `*_images/` folders, and records
unsupported, encrypted, and damaged-file failures without stopping the rest
of a batch. Bundled tools in `resources/bin/` take priority over `PATH`; both
unavailable-tool cases return structured errors instead of crashing.

## Local development

The lightweight frontend can be inspected with:

```powershell
npm install
npm run dev
```

Run the local prerequisite audit and Phase 1 tests with:

```powershell
python scripts/env_check.py
python -m unittest discover -s tests -p "test_*.py" -v
npm run test:frontend
npm run build
python scripts/benchmark_dataset.py
```

Before pushing, enable the versioned hooks once and run the combined gate:

```powershell
git config core.hooksPath .githooks
python scripts/pre_push_check.py
```

Rust/Cargo/MSVC are not required locally. Native Tauri compilation is performed
by `.github/workflows/build.yml` on the GitHub Actions Windows runner.

Version tags matching `v*` create a GitHub Release only after the native tests,
NSIS build, executable verification, and artifact upload succeed.
