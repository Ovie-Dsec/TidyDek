# Changelog

All notable changes to TidyDek are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versioning follows [Semantic Versioning](https://semver.org/).

## [1.0.10] - 2026-07-19

### Fixed
- Headless mode (no tray icon) no longer exits: the main thread now blocks in
  a sleep loop so the daemon threads (watchdog, IPC server) keep the process
  alive, matching the tray-icon behaviour.

## [1.0.9] - 2026-07-19

### Fixed
- The single-instance guard now verifies that the PID it blocks actually
  belongs to a TidyDek process before treating it as a running instance.

## [1.0.8] - 2026-07-19

### Changed
- Tray-icon creation logs every Win32 step at debug level and falls back to a
  headless daemon instead of crashing when the icon cannot be created.

## [1.0.7] - 2026-07-12

### Fixed
- `WNDCLASSW` crash fixed by defining the struct manually instead of relying
  on the ctypes padding.

## [1.0.6] - 2026-07-12

### Changed
- Replaced pystray with a native Win32 tray icon.
- Registry errors are now logged.

## [1.0.5] - 2026-07-10

### Added
- Tray icon with an Exit action.
- Download stability check and PID cleanup.

## [1.0.4] - 2026-07-09

### Fixed
- Autostart used to resolve the wrong exe path; now uses
  `GetModuleFileNameW` for a reliable path.

## [1.0.3] - 2026-07-06

### Fixed
- `organiser.log` is excluded from sorting so the log file no longer triggers
  an endless re-sort loop.

## [1.0.2] - 2026-07-06

### Added
- PowerPoints category and an `organiser.log` log file.
- `--log` flag.

## [1.0.1] - 2026-07-06

### Fixed
- `_1` suffix bug: `get_unique_path` skipped the original destination path, so
  a free name always got a `_1` appended.

## [1.0.0] - 2026-06-25

First release. A Windows daemon that monitors directories and automatically
organizes files into categorized subfolders as they are created or modified.
User-created folders are safely relocated into a master "Folders" directory.
