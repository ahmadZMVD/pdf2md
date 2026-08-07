# Contributing

## Development boundary

This project is offline-first. Lightweight Python, Node.js, Pandoc, and Git
checks run locally. Native Rust/Tauri compilation and Windows packaging run on
GitHub Actions `windows-latest`; do not install or rely on a local Rust/MSVC
toolchain for repository validation.

## Before pushing

Run the configured local gate:

```powershell
python scripts/pre_push_check.py
```

It executes the environment audit, Python/schema tests, browser IPC adapter
tests, and the Vite production build. The repository's hook path is configured
with:

```powershell
git config core.hooksPath .githooks
```

## Commit format

Use a concise subject beginning with one of the supported prefixes:

```text
feat: add conversion queue contract
fix: handle missing pandoc executable
docs: clarify portable packaging boundary
perf: reduce renderer allocations
refactor: isolate IPC command adapter
```

Keep commits focused and avoid mixing generated artifacts with source changes.

## Pull requests

Explain the affected contract, verification evidence, risks, and rollback plan.
Do not include private documents, credentials, or unredacted diagnostic output.
