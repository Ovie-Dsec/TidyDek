"""ScanWorker unit tests: throttling, terminal payload, stop, error paths."""

import queue

import pytest

from src.core.scan_worker import ScanProgress, ScanWorker


def _run_worker(paths, *, progress_every=1, stop_before_start=False):
    """Paths are plain strings; FileInfo tolerates nonexistent files."""
    q = queue.Queue()
    worker = ScanWorker(
        lambda: iter(paths),
        progress_queue=q,
        progress_every=progress_every,
    )
    if stop_before_start:
        worker.stop()
    worker.start()
    events = []
    while True:
        event = q.get(timeout=5)
        events.append(event)
        if event.is_complete:
            break
    assert worker.thread is not None
    worker.thread.join(5)
    return events


def test_terminal_event_carries_sorted_results():
    # Relative names keep this test identical across POSIX/Windows Path norms.
    events = _run_worker(["b.txt", "a.txt", "c.txt"], progress_every=100)
    assert len(events) == 1
    final = events[0]
    assert final.error is None
    assert [f["path"] for f in final.results] == ["a.txt", "b.txt", "c.txt"]
    assert [f["name"] for f in final.results] == ["a.txt", "b.txt", "c.txt"]
    assert final.files_scanned == 3
    assert final.cancelled is False


def test_progress_events_are_throttled():
    paths = [f"/f{i}.txt" for i in range(10)]
    events = _run_worker(paths, progress_every=4)
    mids = [e for e in events if not e.is_complete]
    # mid-events fire at counts 4 and 8; the final file lands in the terminal.
    assert [e.files_scanned for e in mids] == [4, 8]
    terminals = [e for e in events if e.is_complete]
    assert len(terminals) == 1
    assert terminals[0].files_scanned == 10


def test_stop_before_start_yields_cancelled_empty_terminal():
    events = _run_worker(["/a.txt", "/b.txt"], stop_before_start=True)
    final = events[-1]
    assert final.is_complete and final.cancelled
    assert final.results == ()


def test_worker_exception_becomes_error_terminal_not_crash():
    q = queue.Queue()

    def explode():
        raise RuntimeError("disk gone")

    boom = ScanWorker(explode, progress_queue=q)
    boom.start()
    event = q.get(timeout=5)
    assert isinstance(event, ScanProgress)
    assert event.is_complete and event.error is not None
    assert "RuntimeError" in event.error
    assert boom.thread is not None
    boom.thread.join(5)


def test_double_start_is_rejected():
    worker = ScanWorker(lambda: iter([]), progress_queue=queue.Queue())
    worker.start()
    with pytest.raises(RuntimeError):
        worker.start()
