"""Rule-based recursive scanner built on gitignore-style matching.

Design notes (divergences from the original sketch, all deliberate):

- Iterative DFS with branch pruning: the naive ``rglob('*')`` variant
  enumerates the entire tree BEFORE depth/exclude checks run, so max_depth
  never saves any traversal work and cannot prune anything. Here, an excluded
  or over-deep directory is never entered.
- Symlink safety: ``Path.glob``'s recursion does not follow symlinks anyway,
  so the real cycle risk is our own manual descent. Symlinked directories are
  therefore never traversed; symlinked files are treated as regular files.
- Matching uses POSIX-separated relative paths against gitwildmatch specs,
  which is what pathspec expects regardless of platform.
- Yields FILES only; callers needing directories can derive them from the
  results. This matches the existing FileInfo-based ViewModel contract.
- Depth semantics: files directly inside the root are depth 1; a file is out
  of scope when its directory nesting level exceeds ``max_depth``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pathspec

from src.core.config_schema import ScanRules

_DIR_PRUNE_SENTINELS = ("/", "\\")


class FilteredScanner:
    def __init__(self, rules: ScanRules) -> None:
        self._rules = rules
        self._exclude = pathspec.PathSpec.from_lines(
            "gitwildmatch", rules.exclude_patterns
        )
        self._include = pathspec.PathSpec.from_lines(
            "gitwildmatch", rules.include_patterns
        )

    def _is_excluded(self, rel_posix: str, *, is_dir: bool) -> bool:
        if self._exclude.match_file(rel_posix):
            return True
        if is_dir:
            return any(
                self._exclude.match_file(rel_posix + sentinel)
                for sentinel in _DIR_PRUNE_SENTINELS
            )
        return False

    def scan(self, root_path: Path) -> Iterator[Path]:
        root = Path(root_path).resolve()
        if not root.is_dir():
            return
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            current, depth = stack.pop()
            try:
                entries = sorted(current.iterdir())
            except OSError:
                continue  # unreadable branch: skip, never crash the walk
            for entry in entries:
                try:
                    rel_parts = entry.relative_to(root).parts
                except ValueError:
                    continue
                rel_posix = "/".join(rel_parts)
                if entry.is_symlink():
                    if entry.is_dir():
                        continue  # never traverse symlinked directories
                    if self._is_excluded(rel_posix, is_dir=False):
                        continue
                    yield entry
                    continue
                if entry.is_dir():
                    if depth + 1 >= self._rules.max_depth:
                        continue
                    if self._is_excluded(rel_posix, is_dir=True):
                        continue
                    stack.append((entry, depth + 1))
                elif not self._is_excluded(rel_posix, is_dir=False):
                    if self._include.patterns and not self._include.match_file(
                        rel_posix
                    ):
                        continue
                    yield entry
