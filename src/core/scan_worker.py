"""Background scan runner with queue-based progress reporting.

Thread-safety contract (Tkinter is strictly single-threaded):
- The worker NEVER touches widgets or the StateStore. It only pushes
  immutable :class:`ScanProgress` snapshots onto a ``queue.Queue``.
- The UI thread drains that queue from its own timer (CustomTkinter
  ``after()``); all state mutations happen there.

Throughput note: emitting one event per file would flood the queue on large
trees (hundreds of thousands of objects) and starve the UI thread we are
protecting. Progress events are therefore throttled to every
``progress_every`` files; the terminal event always carries the complete,
sorted result set so exactly one final state publication occurs.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from src.core.engine import FileInfo


@dataclass(frozen=True)
class ScanProgress:
    files_scanned: int = 0
    current_path: str = ""
    is_complete: bool = False
    cancelled: bool = False
    error: Optional[str] = None
    results: tuple = field(default=())   # tuple[dict, ...] on completion only


class ScanWorker:
    """Runs a scanner iterable on a daemon thread; communicates via queue."""

    def __init__(
        self,
        file_iterator_factory: Callable[[], Iterable],
        *,
        progress_queue: "queue.Queue[ScanProgress]",
        progress_every: int = 25,
    ) -> None:
        self._factory = file_iterator_factory
        self.queue = progress_queue
        self._progress_every = max(1, progress_every)
        self._stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.thread is not None:
            raise RuntimeError("ScanWorker already started")
        self.thread = threading.Thread(
            target=self._run, name="TidyDekScan", daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _emit(self, **kwargs) -> None:
        self.queue.put(ScanProgress(**kwargs))

    def _run(self) -> None:
        collected: list[dict] = []
        count = 0
        cancelled = False
        try:
            for path in self._factory():
                if self._stop_event.is_set():
                    cancelled = True
                    break
                info = FileInfo(Path(path))
                collected.append(info.as_dict())
                count += 1
                if count % self._progress_every == 0:
                    self._emit(files_scanned=count,
                               current_path=str(path))
        except Exception as exc:
            self._emit(is_complete=True, error=f"{type(exc).__name__}: {exc}")
            return

        results = tuple(sorted(collected, key=lambda f: f["path"]))
        self._emit(
            files_scanned=count,
            is_complete=True,
            cancelled=cancelled,
            results=results,
        )
