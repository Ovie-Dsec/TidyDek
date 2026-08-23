"""Presentation logic binding the Phase 1 core engine to the Phase 3 UI.

MVVM boundary rules enforced here (and by tests/test_architecture.py):
- Imports NOTHING from ``src.gui`` or any GUI toolkit.
- Owns no widgets; all communication flows through the shared StateStore.
- The View renders store snapshots passively and forwards user intents to
  these commands.

Concurrency model (Phase 13): scans run on a background ScanWorker thread.
The worker communicates exclusively through a queue.Queue; ``drain_scan_progress()``
is called from the UI thread's timer and is the ONLY place worker events are
turned into state publications, so Tkinter's single-threaded boundary holds.
``wait_until_idle`` exists for headless tests and tooling that must block on
completion without a UI timer.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from src.core.config_schema import ScanRules
from src.core.engine import DirectoryScanner, FileInfo, FileParser
from src.core.scan_worker import ScanProgress, ScanWorker
from src.core.scanner import FilteredScanner
from src.core.state import Listener, StateStore

DEFAULT_STATE: dict[str, Any] = {
    "root": None,            # str | None: absolute path of the open folder
    "files": [],             # list[dict]: FileInfo.as_dict(), sorted by path
    "selected_index": None,  # int | None: index into "files"
    "preview_text": "",      # str: decoded content, or "" when unavailable
    "status": "Ready.",      # str: human-facing status line
    "busy": False,           # bool: True while a command is running
    "scan_count": 0,         # int: files discovered so far in the active scan
    "scan_current": "",      # str: most recent path reported by the worker
}


class AppViewModel:
    """Headless ViewModel: commands mutate state; the UI merely reacts."""

    def __init__(
        self,
        store: StateStore,
        *,
        parser_extensions: Iterable[str] = (".txt",),
        scan_rules: ScanRules | None = None,
    ) -> None:
        self._store = store
        self._parser_extensions = tuple(parser_extensions)
        self._scan_rules = scan_rules
        self._scan_queue: Optional["queue.Queue[ScanProgress]"] = None
        self._worker: Optional[ScanWorker] = None
        self._idle_event = threading.Event()
        store.replace(dict(DEFAULT_STATE))

    # ---- View-facing observation surface ------------------------------
    def subscribe(self, listener: Listener) -> Callable[[], None]:
        return self._store.subscribe(listener)

    def snapshot(self) -> dict[str, Any]:
        return self._store.snapshot()

    def wait_until_idle(self, timeout: float = 10.0) -> bool:
        """Block until no scan is running; drains progress meanwhile.

        Test/tooling helper: production UI uses its own timer to call
        :meth:`drain_scan_progress` instead of blocking.
        """
        if self._worker is None:
            return True
        expire_at = time.monotonic() + max(0.0, timeout)
        while not self._idle_event.is_set():
            self.drain_scan_progress()
            if self._idle_event.wait(0.02):
                return True
            if time.monotonic() >= expire_at:
                return False
        return True

    # ---- Commands ------------------------------------------------------
    def open_folder(self, path: str | Path) -> bool:
        """Validate ``path`` and start a background scan; returns immediately."""
        root = Path(path).expanduser()
        if not root.is_dir():
            self._store.update_many(
                {
                    "root": None,
                    "files": [],
                    "selected_index": None,
                    "preview_text": "",
                    "busy": False,
                    "scan_count": 0,
                    "scan_current": "",
                    "status": f"Folder not found: {root}",
                }
            )
            return False

        if self._worker is not None and not self._idle_event.is_set():
            self._worker.stop()  # supersede any in-flight scan

        self._idle_event.clear()
        self._scan_queue = queue.Queue()

        scanner: FilteredScanner | DirectoryScanner
        if self._scan_rules is not None:
            scanner = FilteredScanner(self._scan_rules)
        else:
            scanner = DirectoryScanner(root)

        def iterator_factory():
            if isinstance(scanner, FilteredScanner):
                return iter(scanner.scan(root))
            # Legacy scanner returns FileInfo objects; the worker wants paths.
            return iter(info.path for info in scanner.scan())

        self._worker = ScanWorker(
            iterator_factory, progress_queue=self._scan_queue
        )

        self._store.update_many(
            {
                "root": str(root),
                "files": [],
                "selected_index": None,
                "preview_text": "",
                "scan_count": 0,
                "scan_current": "",
                "busy": True,
                "status": f"Scanning {root} ...",
            }
        )
        self._worker.start()
        return True

    def drain_scan_progress(self) -> bool:
        """Consume pending worker events onto the store (UI thread only)."""
        if self._scan_queue is None:
            return False
        had_events = False
        latest_count: Optional[int] = None
        latest_path = ""
        terminal: Optional[ScanProgress] = None

        while True:
            try:
                event: ScanProgress = self._scan_queue.get_nowait()
            except queue.Empty:
                break
            had_events = True
            if event.is_complete:
                terminal = event
            else:
                latest_count = event.files_scanned
                latest_path = event.current_path

        if latest_count is not None:
            self._store.update_many(
                {
                    "scan_count": latest_count,
                    "scan_current": latest_path,
                    "status": f"Scanning... {latest_count} file(s) found",
                }
            )

        if terminal is not None:
            updates: dict[str, Any] = {
                "busy": False,
                "scan_count": terminal.files_scanned,
                "scan_current": "",
                "selected_index": None,
                "preview_text": "",
            }
            if terminal.error:
                updates["status"] = "Scan failed: the folder could not be read."
                updates["files"] = []
            elif terminal.cancelled:
                updates["status"] = (
                    f"Scan cancelled ({terminal.files_scanned} file(s))."
                )
                updates["files"] = list(terminal.results)
            else:
                updates["status"] = f"Loaded {terminal.files_scanned} file(s)."
                updates["files"] = list(terminal.results)
            self._store.update_many(updates)
            self._idle_event.set()
        return had_events

    def cancel_scan(self) -> None:
        """Request cancellation of the in-flight scan (cooperative)."""
        if self._worker is not None:
            self._worker.stop()

    def preview_selected(self, index: int) -> None:
        """Decode and publish a preview of ``files[index]``."""
        files = self._store.get("files") or []
        if isinstance(index, int) and 0 <= index < len(files):
            info = files[index]
            parser = FileParser(list(self._parser_extensions))
            try:
                parsed = parser.parse(FileInfo(Path(info["path"])))
                preview = parsed.get("content", "")
                status = f"Previewing {info['name']}"
            except (OSError, ValueError, UnicodeError):
                preview, status = "", (
                    f"Cannot preview {info['name']} (unsupported or unreadable)."
                )
            self._store.update_many(
                {
                    "selected_index": index,
                    "preview_text": preview,
                    "status": status,
                }
            )
            return
        self._store.update("status", "Nothing to preview.")
