"""Unit tests for the dirty-state tracking engine."""

from src.core.dirty import DirtyStateTracker, diff_states, flatten, state_hash

BASELINE = {"general": {"theme": "dark", "autoscan": True}, "paths": ["C:/a"]}


def test_flatten_produces_dotted_paths():
    assert flatten({"a": {"b": {"c": 1}}, "d": 2}) == {"a.b.c": 1, "d": 2}


def test_clean_when_current_equals_baseline():
    tracker = DirtyStateTracker(BASELINE)
    assert tracker.is_dirty(dict(BASELINE)) is False
    assert tracker.delta(BASELINE) == {"added": {}, "removed": {}, "changed": {}}


def test_dirty_on_nested_change_reports_from_to():
    tracker = DirtyStateTracker(BASELINE)
    current = {"general": {"theme": "light", "autoscan": True}, "paths": ["C:/a"]}
    assert tracker.is_dirty(current) is True
    delta = tracker.delta(current)
    assert delta["changed"] == {"general.theme": {"from": "dark", "to": "light"}}
    assert delta["added"] == {}
    assert delta["removed"] == {}


def test_added_and_removed_keys_detected():
    tracker = DirtyStateTracker({"keep": 1, "drop": 2})
    delta = tracker.delta({"keep": 1, "new": 3})
    assert delta["removed"] == {"drop": 2}
    assert delta["added"] == {"new": 3}
    assert delta["changed"] == {}


def test_mark_clean_promotes_current_to_baseline():
    tracker = DirtyStateTracker(BASELINE)
    current = dict(BASELINE, extra=1)
    assert tracker.is_dirty(current) is True
    tracker.mark_clean(current)
    assert tracker.is_dirty(current) is False
    assert tracker.baseline == current


def test_baseline_property_is_defensive_copy():
    tracker = DirtyStateTracker(BASELINE)
    leaked = tracker.baseline
    leaked["paths"].append("C:/evil")
    assert tracker.baseline["paths"] == ["C:/a"]


def test_state_hash_is_order_independent_and_sensitive_to_change():
    reordered = {"paths": ["C:/a"], "general": {"autoscan": True, "theme": "dark"}}
    different = {"general": {"theme": "light"}}
    assert state_hash(BASELINE) == state_hash(reordered)
    assert state_hash(BASELINE) != state_hash(different)


def test_lists_compare_as_whole_values():
    tracker = DirtyStateTracker({"paths": ["C:/a"]})
    assert tracker.is_dirty({"paths": ["C:/a"]}) is False
    assert tracker.is_dirty({"paths": ["C:/a", "C:/b"]}) is True


def test_diff_states_utility_matches_tracker_delta():
    current = {"general": {"theme": "dark", "autoscan": False}, "extra": True}
    assert diff_states(BASELINE, current)["changed"] == {
        "general.autoscan": {"from": True, "to": False}
    }
    assert diff_states(BASELINE, current)["added"] == {"extra": True}
