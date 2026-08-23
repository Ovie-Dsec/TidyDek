# Changelog

All notable changes to TidyDek are documented here.
The format follows Keep a Changelog; versioning follows Semantic Versioning.
The Single Source of Truth for the current version is `src/version.py`.

## [2.0.0] - 2026-08-23

> **Architectural ground-up rebuild. Supersedes the legacy v1.0.x line.
> Introduces headless-first core, strict MVVM layering, and CustomTkinter UI.**

First production-ready release of the new platform.

### Added
- Threaded scan runner (src/core/scan_worker.py): directory scans execute on
  a daemon thread and report progress through a queue.Queue only; the UI
  thread drains it on a 50 ms timer, so the mainloop can never block or be
  flagged "Not Responding" on huge trees. Progress emission is throttled to
  every 25 files with one authoritative terminal event carrying the full
  sorted result set.
- Windows taskbar progress bridge (src/integrations/taskbar.py): ITaskbarList3
  dispatched through raw vtable entries via the win32_api boundary; scanning
  shows TBPF_INDETERMINATE and clears to TBPF_NOPROGRESS on completion. All
  calls are failure-silent by design.
- AppViewModel async lifecycle: open_folder returns immediately,
  drain_scan_progress publishes worker events onto the store, cancel_scan
  cooperatively stops an in-flight scan, wait_until_idle supports headless
  tests and tooling.
- Main window indeterminate progress bar driven by busy-state transitions.
- Micro-glyph icon strategy: assets/logo_micro.png (auto-derived by tight
  center-crop when absent) exclusively drives the 16px and 32px .ico frames;
  the full logo serves 48px and above, keeping Explorer list view and tray
  rendering crisp at extreme downscale.
- Telemetry closure: the crash dialog now offers "package diagnostics"; on
  confirmation logs and crash artifacts are zipped per session id and the
  default mail client opens pre-addressed to support with the archive path
  in the body.

### Changed
- build.py terminates any running TidyDek.exe before PyInstaller, fixing
  WinError 5 access-denied rebuild failures caused by a locked artifact.
- Root Logo.jpg removed as redundant; assets/logo_source.png is the single
  committed brand source (TIDYDEK_LOGO env remains an explicit override).
- Version bumped to 2.0.0 in src/version.py (SSOT); all consumers derive it.

> The unpublished local "1.0.0" release candidate was re-designated as 2.0.0
> before distribution; the published v1.0.0–v1.0.10 releases on GitHub remain
> the authoritative record of the legacy line.

## [0.2.0] - 2026-08-23

### Added
- GitHub Actions pipeline (.github/workflows/build-and-package.yml) on
  windows-latest: installs project extras, runs the full test suite, builds
  the PyInstaller EXE, compiles the Inno Setup installer (validating ISPP
  version parsing on every push), and uploads both artifacts.
- Rule-based scan engine (src/core/scanner.py): gitignore-style matching via
  pathspec, include and exclude pattern sets, max-depth branch pruning during
  traversal itself, symlinked directories never traversed, unreadable
  branches skipped without crashing.
- Typed scan-rule schema (src/core/config_schema.py) using pydantic:
  ScanRules and AppConfig with bounds-checked max_depth and forward-
  compatible unknown-key tolerance.
- AppViewModel accepts ScanRules; main.py instantiates them from persisted
  settings with safe fallback to schema defaults on malformed data.
- CI workflow integrity tests: YAML validity, trigger coverage, step
  ordering, plain-iscc invocation without version overrides, and absence of
  ghost requirements.txt references.

### Changed
- Settings schema section renamed `scan` to `scan_rules` so persisted
  settings mirror the pydantic ScanRules model exactly; a single source of
  truth for scanning rules now spans settings store, dialog bindings, and
  scanner construction.
- Application and installer iconography now derives deterministically from
  the provided brand logo asset (assets/logo_source.png, sourced from
  Logo.png/Logo.jpg) via build_assets.py, replacing the earlier procedural
  placeholder artwork; the .ico carries all standard resolutions up to the
  logo's native 256px.
- Version bumped to 0.2.0 in src/version.py (SSOT); all consumers derive it.

## [0.1.0] - 2026-08-23

Initial release of the ground-up rebuild (legacy v3.x line fully retired;
no code carried over).

### Added
- Headless core engine: recursive directory scanning with include/exclude
  glob patterns, file metadata collection, and text parsing for supported
  extensions.
- Thread-safe reactive StateStore: deep-copy reads, change-only
  notifications, listener-safe re-entrancy, idempotent unsubscribe.
- Secure configuration persistence: JSON, YAML, and TOML via non-executing
  loaders only, 8 MiB size cap, atomic writes (temp file plus os.replace),
  mapping-root enforcement.
- Dirty-state engine: canonical-hash comparison, dotted-path flattening,
  structured added/removed/changed deltas, baseline promotion.
- CustomTkinter main window (MVVM): reactive rendering driven exclusively by
  ViewModel snapshots; folder scan and text preview flows.
- Windows system tray integration behind strict win32 boundary classes:
  pointer-safe ctypes prototypes (LRESULT/LPARAM as c_ssize_t), lifetime-
  anchored WNDPROC, hidden message window on a dedicated pump thread,
  Shell_NotifyIcon lifecycle, KB135788 focus handling before popup menus.
- Settings dialog wired to the dirty-state engine: Apply enabled only when
  the state-hash delta is non-zero, explicit Tab traversal map, Windows HIG
  button order (OK, Cancel, Apply), Return/Escape shortcuts.
- Architecture purity enforced by AST-based tests: no GUI imports in core or
  viewmodels, View may not bypass the ViewModel layer, ctypes confined to a
  single win32_api module.
- Packaging: src/version.py as the Single Source of Truth consumed by
  pyproject (dynamic version), Inno Setup script via ISPP compile-time
  parsing, and build.py automation (tests, PyInstaller onefile EXE, setup
  build, artifact hashing).
