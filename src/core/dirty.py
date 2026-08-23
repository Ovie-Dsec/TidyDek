"""Dirty-state tracking: baseline vs. current comparison utilities.

Pure functions plus a small tracker class. The Phase 5 Settings dialog will
enable its Apply button only when the delta against the saved baseline is
non-zero, which is exactly what :class:`DirtyStateTracker` answers.

Note on semantics: nested mappings are flattened to dot-separated keys, and an
empty nested mapping contributes nothing. This means ``{"a": {}}`` compares
equal to ``{}`` by design (semantic equality, not structural identity).
Lists compare as whole values and are never flattened.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping

JsonDict = dict[str, Any]


def flatten(mapping: Mapping[str, Any], _prefix: str = "") -> JsonDict:
    """Flatten nested mappings into a single-level dict of dotted paths."""
    flat: JsonDict = {}
    for key, value in mapping.items():
        path = f"{_prefix}.{key}" if _prefix else str(key)
        if isinstance(value, Mapping):
            flat.update(flatten(value, path))
        else:
            flat[path] = value
    return flat


def canonical_json(state: Mapping[str, Any]) -> str:
    """Order-independent canonical JSON rendering of a state mapping."""
    return json.dumps(
        flatten(state), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def state_hash(state: Mapping[str, Any]) -> str:
    """Stable SHA-256 hex digest of the canonical form of ``state``."""
    return hashlib.sha256(canonical_json(state).encode("utf-8")).hexdigest()


def diff_states(
    baseline: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, JsonDict]:
    """Return ``{"added": ..., "removed": ..., "changed": ...}`` deltas.

    ``changed`` entries carry ``{"from": <old>, "to": <new>}``.
    """
    base = flatten(baseline)
    curr = flatten(current)
    added = {k: curr[k] for k in curr.keys() - base.keys()}
    removed = {k: base[k] for k in base.keys() - curr.keys()}
    changed = {
        k: {"from": base[k], "to": curr[k]}
        for k in base.keys() & curr.keys()
        if base[k] != curr[k]
    }
    return {"added": added, "removed": removed, "changed": changed}


class DirtyStateTracker:
    """Tracks whether current state diverges from a stored clean baseline."""

    def __init__(self, baseline: Mapping[str, Any] | None = None) -> None:
        self._baseline: JsonDict = copy.deepcopy(dict(baseline or {}))

    @property
    def baseline(self) -> JsonDict:
        """Deep copy of the stored baseline; safe to inspect or mutate."""
        return copy.deepcopy(self._baseline)

    def mark_clean(self, current: Mapping[str, Any]) -> None:
        """Promote ``current`` to the new clean baseline."""
        self._baseline = copy.deepcopy(dict(current))

    def is_dirty(self, current: Mapping[str, Any]) -> bool:
        """True when ``current`` differs from the baseline in any key."""
        return state_hash(self._baseline) != state_hash(current)

    def delta(self, current: Mapping[str, Any]) -> dict[str, JsonDict]:
        """Structured added/removed/changed delta versus the baseline."""
        return diff_states(self._baseline, current)
