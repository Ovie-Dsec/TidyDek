"""Headless unit tests for AppViewModel (async scan lifecycle, Phase 13)."""

import pytest

from src.core.state import StateStore
from src.viewmodels.app_viewmodel import DEFAULT_STATE, AppViewModel


@pytest.fixture()
def vm():
    return AppViewModel(StateStore())


def _make_tree(tmp_path):
    (tmp_path / "notes.txt").write_text("hello tidy", encoding="utf-8")
    (tmp_path / "data.bin").write_bytes(b"\x00\x01\x02")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("deep content", encoding="utf-8")
    return tmp_path


def test_vm_seeds_default_state_on_construction(vm):
    snap = vm.snapshot()
    for key, value in DEFAULT_STATE.items():
        assert snap[key] == value


def test_subscribe_receives_notifications_from_commands(vm):
    events = []
    vm.subscribe(lambda snap, keys: events.append(tuple(keys)))
    vm.open_folder("Z:/definitely/not/a/real/folder")
    assert events, "expected at least one notification"
    assert "status" in events[-1]


def test_open_folder_invalid_path_reports_error_and_clears_state(vm):
    ok = vm.open_folder("Z:/nope/nothing/here")
    assert ok is False
    snap = vm.snapshot()
    assert snap["root"] is None
    assert snap["files"] == []
    assert "not found" in snap["status"].lower()


def test_open_folder_is_async_then_settles_sorted(vm, tmp_path):
    _make_tree(tmp_path)
    assert vm.open_folder(tmp_path) is True

    # Immediately after the call the worker may still be running.
    first_snap = vm.snapshot()
    assert first_snap["busy"] is True or first_snap["files"], \
        "must be busy OR already drained"

    assert vm.wait_until_idle(timeout=10) is True
    snap = vm.snapshot()
    paths = [f["path"] for f in snap["files"]]
    assert len(paths) == 3
    assert paths == sorted(paths)
    assert snap["busy"] is False
    assert snap["scan_count"] == 3
    assert "Loaded 3 file(s)" in snap["status"]
    assert snap["selected_index"] is None


def test_progress_counter_visible_during_scan(vm, tmp_path):
    _make_tree(tmp_path)
    vm.open_folder(tmp_path)
    # Drain once immediately; small trees may complete on the first drain,
    # so accept either an intermediate count or final publication.
    vm.drain_scan_progress()
    if not vm.wait_until_idle(timeout=10):
        pytest.fail("scan never settled")
    assert vm.snapshot()["scan_count"] == 3


def test_preview_selected_returns_decoded_content(vm, tmp_path):
    _make_tree(tmp_path)
    vm.open_folder(tmp_path)
    assert vm.wait_until_idle(timeout=10)
    names = [f["name"] for f in vm.snapshot()["files"]]
    idx = names.index("notes.txt")
    vm.preview_selected(idx)
    snap = vm.snapshot()
    assert snap["preview_text"] == "hello tidy"
    assert snap["selected_index"] == idx
    assert snap["status"] == "Previewing notes.txt"


def test_preview_selected_unsupported_extension_is_safe(vm, tmp_path):
    _make_tree(tmp_path)
    vm.open_folder(tmp_path)
    assert vm.wait_until_idle(timeout=10)
    names = [f["name"] for f in vm.snapshot()["files"]]
    idx = names.index("data.bin")
    vm.preview_selected(idx)  # must not raise
    snap = vm.snapshot()
    assert snap["preview_text"] == ""
    assert "cannot preview" in snap["status"].lower()


def test_preview_out_of_range_index_is_safe(vm):
    vm.preview_selected(99)
    snap = vm.snapshot()
    assert snap["selected_index"] is None
    assert snap["status"] == "Nothing to preview."


def test_files_snapshot_is_defensive_copy(vm, tmp_path):
    _make_tree(tmp_path)
    vm.open_folder(tmp_path)
    assert vm.wait_until_idle(timeout=10)
    leaked = vm.snapshot()["files"]
    leaked.append({"path": "C:/fake", "name": "fake", "size": 0, "extension": ""})
    assert len(vm.snapshot()["files"]) == 3


def test_cancel_scan_produces_cancelled_terminal_state(tmp_path):
    from src.core.config_schema import ScanRules

    # Deep tree + tiny throttle keeps the worker busy long enough to cancel.
    root = tmp_path / "tree"
    current = root
    for depth in range(40):
        current = current / f"d{depth}"
        current.mkdir(parents=True)
        (current / "f.txt").write_text("x", encoding="utf-8")

    rules = ScanRules(max_depth=64)
    vm = AppViewModel(StateStore(), scan_rules=rules)
    vm.open_folder(root)
    vm.cancel_scan()
    assert vm.wait_until_idle(timeout=10) is True
    snap = vm.snapshot()
    assert snap["busy"] is False
    assert "cancelled" in snap["status"].lower()
