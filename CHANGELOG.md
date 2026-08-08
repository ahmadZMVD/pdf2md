# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and releases use semantic versioning.

## [Unreleased]

### Fixed

- Cancellation now kills the in-flight engine process immediately via a parked
  child-process handle; queued items are never started afterwards.
- Engine stdout/stderr stream to temporary log files instead of RAM buffers.
- Python conversion watchdog terminates stuck conversions with a hard timeout.
- Image extraction succeeds for output directories containing spaces; links
  are relinked from actual on-disk files with forward slashes.
- Math notation is preserved at the Pandoc AST level with a Lua filter;
  inline code spans containing dollars and currency values are never touched.
- Failed Pandoc runs delete partial output files.
- Browser IPC mock returns `null` output paths for unsupported formats,
  matching native Rust semantics.
- Persian RTL fixture embeds a real Arabic-script font and asserts Unicode
  codepoints in the U+0600-U+06FF range.

### Changed

- Benchmark fixtures regenerated as multi-page documents above a 3,000
  character floor, plus scanned-photo and mixed-script documents.
- Native Rust tests run in the debug profile with an isolated cache key so
  test builds never churn the release cache.
- Release cargo cache keyed explicitly by the Cargo.lock hash.
- Warm Rust cache reuse verified across consecutive Windows CI runs.
- Release compilation switched to parallel no-LTO codegen for the fastest CI links.
- Tauri bundler tools cached and NSIS compression set to fast zlib.

### Added

- Pandoc Lua filter at `scripts/filters/math_preserve.lua`, bundled in the
  application resources.
- Statistical benchmark dataset tests with per-format character floors and
  Arabic-script codepoint range assertions.
- Browser-safe IPC adapter with deterministic healthcheck mocks.
- Rust dependency and target caching in the Windows CI workflow.
- Portfolio issue, pull request, contribution, and security standards.
- Portable packaging roadmap for a zero-external-dependency installer.

## [0.1.0] — 2026-08-06

### Added

- Fixed-size Tauri v2 shell at 380×520 with dark theme and tray lifecycle.
- Dynamic Rust system healthcheck command.
- Cloud Windows NSIS build and downloadable executable artifact.
