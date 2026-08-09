# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and releases use semantic versioning.

## [Unreleased]

### Added

- Apple HIG light-bone (off-white `#F5F5F7`) visual system with white cards,
  liquid glass dragzone and deep soft shadows.
- Custom frameless window: integrated off-white titlebar with linear
  minimize / maximize-restore / close-to-tray controls and drag regions.
- Apple segmented controls replacing the two-option dropdowns (format,
  destination, PDF images) with a sliding white thumb on a `#E4E4E6` track.
- Dynamic queue collapse: the glass dragzone compresses into a thin top bar
  the moment files are queued, keeping 4+ cards visible before scrolling.
- Native folder picker via `pick_output_folder` (dialog plugin); the settings
  modal no longer hardcodes `C:/converted`.
- Per-item retry for failed conversions: a failed batch immediately unlocks
  Clear List, resets the action bar, and renders `↻ Retry` on failed cards.
- Headless real-layout verification (`npm run test:ui-layout`) covering
  overflow, dragzone, segmented controls, modal stacking and the unlock
  state machine in Edge over CDP (31 checks).

### Changed

- Window bounds expanded from 380×520 to 440×620, still fixed-size, and now
  frameless (`decorations: false`) with the light theme.
- Status badges renamed to the minimal vocabulary (Done / Skip / Unsupported).
- Focus rings and modal chrome rounded to match the input geometry; the
  settings backdrop now stacks at z-50 with the panel at z-51.

### Fixed

- Settings modal backdrop no longer slices underlying window labels and
  dropdowns through the panel.
- `Save Settings` text is centered inside its container with generous
  padding instead of overflowing.
- Conversion failure no longer leaves the queue locked: the state machine
  unlocks immediately and retry re-enables Convert All.
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
