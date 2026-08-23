"""Headless settings engine: editing, dirty tracking, atomic persistence.

Flow: the View mutates the working copy through :meth:`update_field`; every
mutation recomputes dirtiness against the saved baseline using the Phase 2
dirty-state engine (canonical-hash comparison, so "Apply enabled" literally
means the state-hash delta is non-zero). ``apply()`` writes atomically via
the Phase 2 ConfigManager and promotes the working copy to the new baseline;
``discard()`` reverts to it.

Resilience policy: a missing OR unreadable/corrupt config file falls back to
built-in defaults instead of crashing startup; detailed telemetry arrives
with the Phase 6 logging work.
"""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol

from src.core.config import ConfigError, ConfigManager
from src.core.dirty import DirtyStateTracker
from src.core.state import Listener, StateStore

DEFAULT_SETTINGS: dict[str, Any] = {
    "general": {"theme": "System", "autoscan_on_open": False},
    # Mirrors src.core.config_schema.ScanRules exactly; validation happens
    # when the app instantiates ScanRules from this persisted dict.
    "scan_rules": {
        "exclude_patterns": [],
        "include_patterns": ["**/*"],
        "max_depth": 10,
    },
}


def default_config_path() -> Path:
    """%APPDATA%/TidyDek/settings.json (home fallback for odd environments)."""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home()
    return root / "TidyDek" / "settings.json"


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _set_nested(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    node = target
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


AppliedCallback = Callable[[dict[str, Any]], None]


class ConfigStoreLike(Protocol):
    """Capability the settings engine needs; ConfigManager satisfies it."""

    def load(self) -> dict[str, Any]: ...

    def save(self, data: dict[str, Any]) -> None: ...


class SettingsViewModel:
    """Owns working settings, their clean baseline, and the save pipeline."""

    def __init__(
        self,
        *,
        config_manager: Optional[ConfigStoreLike] = None,
        on_applied: Optional[AppliedCallback] = None,
        store: Optional[StateStore] = None,
    ) -> None:
        self._cm = config_manager
        self._on_applied = on_applied
        self._store = store if store is not None else StateStore()
        self._tracker = DirtyStateTracker(self._load_baseline())
        self._publish(
            working=self._tracker.baseline,
            dirty=False,
            status="Settings loaded.",
        )

    # ------------------------------------------------------- observation
    def subscribe(self, listener: Listener) -> Callable[[], None]:
        return self._store.subscribe(listener)

    def snapshot(self) -> dict[str, Any]:
        return self._store.snapshot()

    # ---------------------------------------------------------- commands
    def update_field(self, dotted_path: str, value: Any) -> None:
        """Set one nested field (e.g. ``"general.theme"``) on the copy."""
        working = self._store.get("working") or {}
        _set_nested(working, dotted_path, copy.deepcopy(value))
        dirty = self._tracker.is_dirty(working)
        self._publish(
            working=working,
            dirty=dirty,
            status="Unsaved changes." if dirty else "Settings loaded.",
        )

    def apply(self) -> bool:
        """Persist the working copy; True only when a real change was saved."""
        working = self._store.get("working") or {}
        if not self._tracker.is_dirty(working):
            self._store.update("status", "Nothing to save.")
            return False
        if self._cm is None:
            self._store.update("status", "Persistence unavailable.")
            return False
        try:
            self._cm.save(working)
        except ConfigError:
            # Friendly client message; raw OS detail stays out of the dialog.
            self._store.update("status", "Save failed: settings file is not writable.")
            return False
        self._tracker.mark_clean(working)
        self._publish(working=working, dirty=False, status="Settings saved.")
        if self._on_applied is not None:
            try:
                self._on_applied(copy.deepcopy(working))
            except Exception as exc:  # consumer hook problems never block saving
                sys.stderr.write(f"settings on_applied error: {exc!r}\n")
        return True

    def discard(self) -> None:
        """Revert the working copy to the last saved baseline."""
        self._publish(
            working=self._tracker.baseline,
            dirty=False,
            status="Changes discarded.",
        )

    # --------------------------------------------------------- internals
    def _load_baseline(self) -> dict[str, Any]:
        merged = copy.deepcopy(DEFAULT_SETTINGS)
        if self._cm is not None:
            try:
                data = self._cm.load()
            except FileNotFoundError:
                data = {}
            except ConfigError:
                data = {}  # corrupt file: fall back to defaults
            if isinstance(data, dict) and data:
                merged = _deep_merge(merged, data)
        return merged

    def _publish(self, *, working: dict[str, Any], dirty: bool, status: str) -> None:
        self._store.update_many(
            {
                "working": copy.deepcopy(working),
                "dirty": dirty,
                "status": status,
            }
        )
