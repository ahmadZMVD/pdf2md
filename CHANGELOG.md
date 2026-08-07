# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and releases use semantic versioning.

## [Unreleased]

### Changed

- Warm Rust cache reuse verified across consecutive Windows CI runs.
- Release compilation switched to parallel no-LTO codegen for the fastest CI links.
- Tauri bundler tools cached and NSIS compression set to fast zlib.

### Added

- Browser-safe IPC adapter with deterministic healthcheck mocks.
- Rust dependency and target caching in the Windows CI workflow.
- Portfolio issue, pull request, contribution, and security standards.
- Portable packaging roadmap for a zero-external-dependency installer.

## [0.1.0] — 2026-08-06

### Added

- Fixed-size Tauri v2 shell at 380×520 with dark theme and tray lifecycle.
- Dynamic Rust system healthcheck command.
- Cloud Windows NSIS build and downloadable executable artifact.
