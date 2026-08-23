"""Phase 19.2: First Run Experience — trigger matrix and dismissal lifecycle."""

import queue
from types import SimpleNamespace

from src.core.config_schema import ScanRules
from src.core.scan_worker import ScanProgress
from src.core.state import StateStore
from src.viewmodels.app_viewmodel import AppViewModel, is_first_run


# ------------------------------------------------------------ trigger logic
def test_fre_triggers_on_missing_config_and_no_marker(tmp_path):
    config = tmp_path / "settings.json"
    marker = tmp_path / ".first_run_complete"
    assert is_first_run(config, marker) is True


def test_fre_suppressed_when_config_exists(tmp_path):
    config = tmp_path / "settings.json"
    marker = tmp_path / ".first_run_complete"
    config.write_text("{}", encoding="utf-8")
    assert is_first_run(config, marker) is False


def test_fre_permanently_suppressed_by_marker_even_without_config(tmp_path):
    config = tmp_path / "settings.json"
    marker = tmp_path / ".first_run_complete"
    marker.write_text("dismissed", encoding="utf-8")
    assert is_first_run(config, marker) is False  # survives restarts
    assert is_first_run(None, marker) is False


def _make_tree(tmp_path):
    (tmp_path / "notes.txt").write_text("welcome", encoding="utf-8")
    return tmp_path


def _make_vm(first_run=True, on_done=None):
    return AppViewModel(
        StateStore(), first_run=first_run, on_first_scan_completed=on_done
    )


# --------------------------------------------------------- dismissal cycle
def test_successful_scan_dismisses_fre_and_fires_callback_once(tmp_path):
    fired = []
    vm = _make_vm(on_done=lambda: fired.append(1))
    assert vm.snapshot()["first_run"] is True

    vm.open_folder(_make_tree(tmp_path))
    assert vm.wait_until_idle(timeout=10)

    snap = vm.snapshot()
    assert snap["first_run"] is False
    assert fired == [1]

    # Latch: a second scan must not re-fire the callback.
    vm.open_folder(tmp_path)
    assert vm.wait_until_idle(timeout=10)
    assert vm.snapshot()["first_run"] is False
    assert fired == [1]


def test_cancelled_scan_does_not_dismiss_fre(tmp_path):
    root = tmp_path / "tree"
    current = root
    for depth in range(40):
        current = current / f"d{depth}"
        current.mkdir(parents=True)
        (current / "f.txt").write_text("x", encoding="utf-8")

    fired = []
    vm = AppViewModel(
        StateStore(),
        scan_rules=ScanRules(max_depth=64),
        first_run=True,
        on_first_scan_completed=lambda: fired.append(1),
    )
    vm.open_folder(root)
    vm.cancel_scan()
    assert vm.wait_until_idle(timeout=10)

    snap = vm.snapshot()
    assert snap["busy"] is False
    assert snap["first_run"] is True, "cancelled scan must not end FRE"
    assert fired == []


def test_error_terminal_does_not_dismiss_fre():
    fired = []
    vm = _make_vm(on_done=lambda: fired.append(1))
    # White-box: inject an error terminal exactly as a failed worker would.
    vm._scan_queue = queue.Queue()
    vm._worker = SimpleNamespace()  # type: ignore[assignment]
    vm._scan_queue.put(
        ScanProgress(is_complete=True, error="RuntimeError: injected")
    )
    vm.drain_scan_progress()

    snap = vm.snapshot()
    assert snap["first_run"] is True
    assert snap["busy"] is False
    assert "failed" in snap["status"].lower()
    assert fired == []


def test_default_construction_has_fre_off():
    vm = AppViewModel(StateStore())
    assert vm.snapshot()["first_run"] is False
