"""Central reactive state store for TidyDek.

Thread-safe and UI-agnostic. GUI layers (Phase 3+) observe this store;
nothing here imports or knows about any presentation layer.

Contract:
- Reads (``get``/``snapshot``) return deep copies, so callers can never
  corrupt internal state.
- Writes (``update``/``update_many``/``replace``) notify subscribers only
  for keys whose value actually changed.
- Listeners receive ``(snapshot, changed_keys)`` and run outside the
  internal lock; a listener may safely call back into the store.
- An exception raised inside a listener propagates to the writer.
- Registering the same listener object twice is a no-op.
"""

from __future__ import annotations

import copy
import threading
from typing import Any, Callable, Mapping

StateSnapshot = Mapping[str, Any]
Listener = Callable[[StateSnapshot, "tuple[str, ...]"], None]

_MISSING = object()


class StateStore:
    """Minimal reactive key-value store with change notifications."""

    def __init__(self, initial_state: Mapping[str, Any] | None = None) -> None:
        self._lock = threading.RLock()
        self._state: dict[str, Any] = copy.deepcopy(dict(initial_state or {}))
        self._listeners: list[Listener] = []

    # ---- reads ---------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key not in self._state:
                return copy.deepcopy(default)
            return copy.deepcopy(self._state[key])

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)

    # ---- writes ----------------------------------------------------------
    def update(self, key: str, value: Any) -> None:
        self.update_many({key: value})

    def update_many(self, updates: Mapping[str, Any]) -> None:
        incoming = dict(updates)
        with self._lock:
            changed = [
                key
                for key, value in incoming.items()
                if key not in self._state or self._state[key] != value
            ]
            if not changed:
                return
            for key in changed:
                self._state[key] = copy.deepcopy(incoming[key])
            snap = copy.deepcopy(self._state)
        self._notify(snap, tuple(changed))

    def replace(self, state: Mapping[str, Any]) -> None:
        """Atomically swap the entire state, reporting every delta."""
        incoming = copy.deepcopy(dict(state))
        with self._lock:
            keys = set(incoming) | set(self._state)
            changed = [
                key
                for key in keys
                if self._state.get(key, _MISSING) != incoming.get(key, _MISSING)
            ]
            self._state = incoming
            if not changed:
                return
            snap = copy.deepcopy(self._state)
        self._notify(snap, tuple(changed))

    # ---- subscriptions ---------------------------------------------------
    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Register ``listener``; returns an idempotent unsubscribe callable."""
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._listeners.remove(listener)
                except ValueError:
                    pass

        return unsubscribe

    # ---- internals ---------------------------------------------------------
    def _notify(self, snapshot: dict[str, Any], changed: tuple[str, ...]) -> None:
        for listener in tuple(self._listeners):
            listener(snapshot, changed)
