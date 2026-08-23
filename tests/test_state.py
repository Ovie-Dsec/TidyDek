"""Unit tests for the central reactive StateStore."""

from src.core.state import StateStore


def test_initial_state_and_get_with_default():
    store = StateStore({"theme": "dark"})
    assert store.get("theme") == "dark"
    assert store.get("missing", "fallback") == "fallback"
    assert store.get("missing") is None


def test_snapshot_is_deep_copy_in_both_directions():
    original = {"nested": {"a": [1, 2]}}
    store = StateStore(original)
    snap = store.snapshot()
    snap["nested"]["a"].append(3)          # mutate outward copy
    assert store.get("nested") == {"a": [1, 2]}
    original["nested"]["a"].append(9)      # mutate source after construction
    assert store.get("nested") == {"a": [1, 2]}
    got = store.get("nested")
    got["a"].append(99)                    # mutate value returned by get()
    assert store.get("nested") == {"a": [1, 2]}


def test_update_notifies_with_snapshot_and_changed_key():
    store = StateStore({"count": 1})
    seen = []
    unsub = store.subscribe(lambda snap, keys: seen.append((snap["count"], keys)))
    store.update("count", 2)
    assert seen == [(2, ("count",))]
    unsub()


def test_update_skips_notification_when_value_unchanged():
    store = StateStore({"flag": True})
    calls = []
    store.subscribe(lambda snap, keys: calls.append(keys))
    store.update("flag", True)
    assert calls == []


def test_update_many_notifies_once_with_all_changed_keys():
    store = StateStore()
    calls = []
    store.subscribe(lambda snap, keys: calls.append(keys))
    store.update_many({"a": 1, "b": 2})
    assert len(calls) == 1
    assert set(calls[0]) == {"a", "b"}


def test_unsubscribe_stops_notifications_and_is_idempotent():
    store = StateStore()
    calls = []
    unsub = store.subscribe(lambda snap, keys: calls.append(keys))
    unsub()
    unsub()  # second call must be a no-op, not an error
    store.update("x", 1)
    assert calls == []


def test_replace_reports_added_removed_and_changed_keys():
    store = StateStore({"a": 1, "b": 2})
    calls = []
    store.subscribe(lambda snap, keys: calls.append(keys))
    store.replace({"b": 3, "c": 4})
    assert set(calls[0]) == {"a", "b", "c"}
    assert store.snapshot() == {"b": 3, "c": 4}


def test_listener_may_safely_call_back_into_store():
    store = StateStore({"n": 0})
    observed = []

    def listener(snapshot, keys):
        observed.append(store.get("n"))  # re-entrant read during notify

    store.subscribe(listener)
    store.update("n", 5)
    assert observed == [5]


def test_duplicate_subscribe_does_not_double_notify():
    store = StateStore()
    calls = []

    def listener(snapshot, keys):
        calls.append(keys)

    store.subscribe(listener)
    store.subscribe(listener)  # same listener registered twice on purpose
    store.update("x", 1)
    assert len(calls) == 1
