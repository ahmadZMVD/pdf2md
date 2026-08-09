# Phase 3.1 & 3.2 Overhaul Report — Apple Light Bone UI & Frameless Shell

**Repository:** `ahmadZMVD/pdf2md` · **Branch:** `main` · **Head:** `49a5753`
**Status:** `completed` · **Verification:** `apple_light_bone_ui_and_frameless_shell_verified`

## 1. What changed

| Area | Before (3.1) | After (3.2) |
| --- | --- | --- |
| Theme | Deep dark `#0D0D0E` | Apple HIG off-white/bone `#F5F5F7`, white cards, `0 4px 20px rgba(0,0,0,.04)` shadows |
| Dragzone | Dashed border always visible | Liquid glassmorphism `blur(16px) saturate(180%)`; dashed border only while dragging, animated in/out |
| Window | 380×520, native Windows titlebar, dark | 440×620 fixed, `decorations: false`, custom off-white titlebar with linear minimize / maximize-restore / close-to-tray icons |
| Option controls | Heavy `<select>` dropdowns | Apple segmented controls with a sliding white thumb on a `#E4E4E6` track (format, destination, PDF images) |
| Queue | Single-card view sandwiched between dropzone and actions | Dropzone collapses to a 42px thin bar; **5 cards** visible before internal scrolling |
| Settings modal | Z-slicing, overflowing Save text, square focus ring, dummy `Browse…` → `C:/converted` | Backdrop z-50 / panel z-51, centered Save text, rounded focus ring, real native folder picker via the dialog plugin |
| Failure handling | Frozen `Convert All` after a failed file | Per-item `↻ Retry`, immediate unlock of Clear List, retry re-enables Convert All |
| Badges | Full status words | Minimal vocabulary: Queued · Converting · Done · Failed · Unsupported · Skip |

## 2. Local verification (real execution)

- **IPC adapter tests:** 34/34 passed
- **Queue store tests:** 65/65 passed (incl. new retry/unlock state-machine scenarios)
- **Python schema/workflow tests:** 23/23 passed (window contract updated to 440×620 frameless light)
- **Production build:** success, 1.6s, zero Vite/Tailwind errors
- **Headless real-layout verification** (`npm run test:ui-layout`, Edge over CDP at pinned 440×620): **31/31 checks passed** — viewport/overflow, dragzone idle vs dragover dashed border, segmented thumb slide, modal z-stacking, queue collapse (5 cards visible), failed-batch unlock with retry

## 3. Cloud build (GitHub Actions)

- **Run:** `31288828117` · **Duration:** 394 s · **Conclusion:** `success`
- `quality` job: success · `build-windows` job: success (native Rust tests, NSIS installer, executable verification, artifact upload)
- **Artifact:** `PDF-Converter-Windows-EXE` — 1.78 MB, not expired

## 4. Adversarial critique log (real iterations)

| Task | Failed attempts | Root cause | Alternative path |
| --- | --- | --- | --- |
| Fixed 440×620 headless viewport | 2 | Headless chrome reports outer-window size (492×491) | CDP `Emulation.setDeviceMetricsOverride` |
| Loading the built frontend | 1 | ES modules CORS-blocked from `file://` | Minimal `node:http` static server |
| Backdrop stacking | 1 | No explicit z-index on backdrop | z-50 backdrop, z-51 panel |
| Stable Edge session | 1 | Locked profile dir → exit code 21 | Per-PID profile + cleanup in `finally` |
| Query-navigation state B | 1 | Stale `pageUrl(query)` call sites | Signature fix `pageUrl(port, query)` |
| Retry contract | 1 | Test expected completed items to reset | Asserted real contract: failed-only retry |

Feature degradation for every alternative path: **0.0%**.

## 5. Git delivery gate

- ✅ 4 semantic commits pushed to `main` (`feat:`, `feat:`, `fix:`, `docs:`)
- ✅ GitHub Actions completed `SUCCESS`
- ✅ Native executable artifact generated and downloadable

## 6. Identified limitations

- `Cargo.lock` is regenerated deterministically by CI (no local Rust by design).
- Browser mock folder picker returns `null`; real dialog is native-shell-only.
- `npm run test:ui-layout` resolves Edge from fixed paths → local-machine verification (CI runs the Node/Python equivalents).
- `gh` must be invoked by full path on this machine (`System32\gh.exe` shadows PATH).
- Close-to-tray is the only close behavior; full exit lives in the tray menu, per PROMPT 0.
