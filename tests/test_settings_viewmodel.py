"""Headless tests for the settings engine (no GUI toolkit involved)."""

import pytest

from src.core.config import ConfigError, ConfigManager
from src.viewmodels.settings_viewmodel import (
    DEFAULT_SETTINGS,
    SettingsViewModel,
    default_config_path,
)


@pytest.fixture()
def config(tmp_path):
    return ConfigManager(tmp_path / "settings.json")


@pytest.fixture()
def vm(config):
    return SettingsViewModel(config_manager=config)


# ------------------------------------------------------------ construction
def test_initial_state_matches_defaults_and_is_clean(vm):
    snap = vm.snapshot()
    assert snap["working"] == DEFAULT_SETTINGS
    assert snap["dirty"] is False
    assert snap["status"] == "Settings loaded."


def test_missing_file_behaves_like_defaults(config):
    # No file written yet; construction must not raise.
    vm = SettingsViewModel(config_manager=config)
    assert vm.snapshot()["working"] == DEFAULT_SETTINGS


def test_partial_saved_config_merges_over_defaults(config, tmp_path):
    config.save({"general": {"theme": "Dark"}})
    vm = SettingsViewModel(config_manager=config)
    expected = {
        "general": {"theme": "Dark", "autoscan_on_open": False},
        "scan_rules": {
            "exclude_patterns": [],
            "include_patterns": ["**/*"],
            "max_depth": 10,
        },
    }
    assert vm.snapshot()["working"] == expected


def test_corrupt_config_falls_back_to_defaults(config, tmp_path):
    config.path.write_text("{not valid json!!", encoding="utf-8")
    vm = SettingsViewModel(config_manager=config)
    assert vm.snapshot()["working"] == DEFAULT_SETTINGS


def test_default_config_path_uses_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", r"D:\AppData\Roaming")
    path = default_config_path()
    assert str(path).lower().startswith(r"d:\appdata\roaming")
    assert path.name == "settings.json"
    assert path.parent.name == "TidyDek"


# ------------------------------------------------------------- dirty cycle
def test_update_field_flips_dirty_and_reverting_restores_hash_equality(vm):
    assert vm.snapshot()["dirty"] is False
    vm.update_field("general.theme", "Dark")
    assert vm.snapshot()["dirty"] is True
    assert "Unsaved" in vm.snapshot()["status"]
    vm.update_field("general.theme", "System")  # hash-delta back to zero
    assert vm.snapshot()["dirty"] is False


def test_nested_list_field_round_trips(vm):
    vm.update_field("scan_rules.exclude_patterns", ["*.tmp", "node_modules"])
    working = vm.snapshot()["working"]
    assert working["scan_rules"]["exclude_patterns"] == ["*.tmp", "node_modules"]
    assert working["general"]["theme"] == "System"  # untouched section intact


def test_discard_reverts_everything_to_baseline(vm):
    original = vm.snapshot()["working"]
    vm.update_field("general.autoscan_on_open", True)
    vm.update_field("scan.exclude_patterns", ["x"])
    vm.discard()
    snap = vm.snapshot()
    assert snap["working"] == original
    assert snap["dirty"] is False


# ------------------------------------------------------------------ apply
def test_apply_persists_clears_dirty_and_survives_reload(vm):
    vm.update_field("general.theme", "Dark")
    vm.update_field("general.autoscan_on_open", True)
    assert vm.apply() is True
    after = vm.snapshot()
    assert after["dirty"] is False
    assert after["status"] == "Settings saved."

    fresh = SettingsViewModel(config_manager=vm._cm)
    reloaded = fresh.snapshot()["working"]
    assert reloaded["general"]["theme"] == "Dark"
    assert reloaded["general"]["autoscan_on_open"] is True


def test_apply_with_no_changes_returns_false_and_reports(vm):
    assert vm.apply() is False
    assert vm.snapshot()["status"] == "Nothing to save."
    assert vm.snapshot()["dirty"] is False


class _ExplodingConfigManager:
    """Stub whose save() always fails, for the failure-path test."""

    def __init__(self):
        self.calls = 0

    def load(self):
        return {}

    def save(self, data):
        self.calls += 1
        raise ConfigError("simulated unwritable target")


def test_failed_save_keeps_dirty_and_skips_callback():
    boom = _ExplodingConfigManager()
    applied = []
    vm = SettingsViewModel(
        config_manager=boom, on_applied=lambda snap: applied.append(snap)
    )
    vm.update_field("general.theme", "Light")
    assert vm.apply() is False
    snap = vm.snapshot()
    assert snap["dirty"] is True                       # still unsaved
    assert "failed" in snap["status"].lower()
    assert boom.calls == 1                             # exactly one attempt
    assert applied == []                               # hook not fired


def test_hook_not_fired_when_persistence_unavailable():
    seen = []
    vm = SettingsViewModel(on_applied=lambda snap: seen.append(snap))
    vm.update_field("scan.exclude_patterns", ["a", "b"])
    assert vm.apply() is False                      # no ConfigManager wired
    assert vm.snapshot()["status"] == "Persistence unavailable."
    assert seen == []                               # hook never fired


def test_on_applied_hook_fires_only_after_real_persist(config):
    seen = []
    vm = SettingsViewModel(config_manager=config,
                           on_applied=lambda snap: seen.append(snap))
    vm.update_field("general.theme", "Light")
    assert vm.apply() is True
    assert len(seen) == 1
    assert seen[0]["general"]["theme"] == "Light"
