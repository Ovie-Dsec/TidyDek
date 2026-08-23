"""Unit tests for the pathspec-based FilteredScanner."""

from pathlib import Path

import pytest

from src.core.config_schema import ScanRules
from src.core.scanner import FilteredScanner


def _names(root: Path, rules: ScanRules) -> set[str]:
    return {p.name for p in FilteredScanner(rules).scan(root)}


def _make_tree(tmp_path: Path) -> Path:
    (tmp_path / "keep.txt").write_text("a", encoding="utf-8")
    (tmp_path / "junk.tmp").write_text("b", encoding="utf-8")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "module.pyc").write_bytes(b"\x00")
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    (nested / "impl.txt").write_text("c", encoding="utf-8")
    return tmp_path


def test_exclude_prunes_directories_and_files(tmp_path):
    _make_tree(tmp_path)
    rules = ScanRules(exclude_patterns=["__pycache__/", "*.tmp"])
    found = _names(tmp_path, rules)
    assert found == {"keep.txt", "impl.txt"}
    assert "module.pyc" not in found
    assert "junk.tmp" not in found


def test_nested_glob_exclusion(tmp_path):
    (tmp_path / "keep.py").write_text("x", encoding="utf-8")
    vendor = tmp_path / "vendor" / "lib"
    vendor.mkdir(parents=True)
    (vendor / "thing.js").write_text("y", encoding="utf-8")
    rules = ScanRules(exclude_patterns=["**/vendor/**"])
    assert _names(tmp_path, rules) == {"keep.py"}


def test_include_patterns_restrict_reported_files(tmp_path):
    _make_tree(tmp_path)
    rules = ScanRules(include_patterns=["*.txt"])
    assert _names(tmp_path, rules) == {"keep.txt", "impl.txt"}


def test_max_depth_one_reports_only_root_level_files(tmp_path):
    _make_tree(tmp_path)
    rules = ScanRules(max_depth=1)
    assert _names(tmp_path, rules) == {"keep.txt", "junk.tmp"}


def test_max_depth_two_reaches_one_nested_level(tmp_path):
    _make_tree(tmp_path)
    shallow = tmp_path / "mid"
    shallow.mkdir()
    (shallow / "mid.txt").write_text("m", encoding="utf-8")
    deep = tmp_path / "mid" / "low"
    deep.mkdir()
    (deep / "low.txt").write_text("l", encoding="utf-8")

    depth2 = ScanRules(max_depth=2)
    assert "mid.txt" in _names(tmp_path, depth2)
    assert "low.txt" not in _names(tmp_path, depth2)

    depth3 = ScanRules(max_depth=3)
    assert {"mid.txt", "low.txt"} <= _names(tmp_path, depth3)


def test_symlinked_directories_are_never_traversed(tmp_path):
    real = tmp_path / "real_dir"
    real.mkdir()
    (real / "inside.txt").write_text("i", encoding="utf-8")
    link = tmp_path / "link_to_real"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation requires developer mode/admin here")
    rules = ScanRules()
    rel_paths = [
        p.relative_to(tmp_path).as_posix() for p in FilteredScanner(rules).scan(tmp_path)
    ]
    # Content reachable via its REAL location must still be reported...
    assert "real_dir/inside.txt" in rel_paths
    # ...but never duplicated through the symlinked directory.
    assert all(not rp.startswith("link_to_real/") for rp in rel_paths)


def test_unreadable_directory_is_skipped_without_crash(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "secret.txt").write_text("s", encoding="utf-8")
    rules = ScanRules()
    scanner = FilteredScanner(rules)

    original_iterdir = Path.iterdir

    def guarded(self):
        if self.name == "locked":
            raise PermissionError(13, "simulated ACL block")
        return original_iterdir(self)

    import pathlib

    pathlib.Path.iterdir = guarded
    try:
        found = {p.name for p in scanner.scan(tmp_path)}
    finally:
        pathlib.Path.iterdir = original_iterdir
    assert found == set() or "secret.txt" not in found
