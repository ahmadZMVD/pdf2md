# PDF & Document Converter

Phase 1 establishes the fixed-size Tauri v2 desktop shell and the cloud-only
Windows build gate. Document conversion engines are intentionally deferred to a
later phase.

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
```

Rust/Cargo/MSVC are not required locally. Native Tauri compilation is performed
by `.github/workflows/build.yml` on the GitHub Actions Windows runner.
