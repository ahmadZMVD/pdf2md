# PDF & Document Converter

The current Phase 1.5 foundation provides a fixed-size Tauri v2 desktop shell,
a browser-safe IPC adapter, and a cloud-only Windows build and release gate.
Document conversion engines are intentionally deferred to a later phase.

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
