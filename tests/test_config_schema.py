"""Unit tests for the pydantic scan-rule schema."""

import pytest
from pydantic import ValidationError

from src.core.config_schema import AppConfig, ScanRules


def test_defaults_match_documented_contract():
    rules = ScanRules()
    assert rules.exclude_patterns == []
    assert rules.include_patterns == ["**/*"]
    assert rules.max_depth == 10


def test_max_depth_bounds_enforced():
    with pytest.raises(ValidationError):
        ScanRules(max_depth=0)
    with pytest.raises(ValidationError):
        ScanRules(max_depth=65)
    assert ScanRules(max_depth=1).max_depth == 1
    assert ScanRules(max_depth=64).max_depth == 64


def test_unknown_keys_are_ignored_for_forward_compatibility():
    rules = ScanRules(**{"exclude_patterns": ["x"], "future_field": 123})
    assert rules.exclude_patterns == ["x"]
    assert not hasattr(rules, "future_field")


def test_appconfig_nests_scan_rules():
    cfg = AppConfig(scan_rules={"exclude_patterns": ["*.tmp"], "max_depth": 3})
    assert isinstance(cfg.scan_rules, ScanRules)
    assert cfg.scan_rules.exclude_patterns == ["*.tmp"]
    assert cfg.scan_rules.max_depth == 3


def test_model_dump_round_trips_into_constructor():
    original = ScanRules(exclude_patterns=["a", "b/"], max_depth=5)
    restored = ScanRules(**original.model_dump())
    assert restored == original


def test_list_coercion_rejects_non_string_entries():
    with pytest.raises(ValidationError):
        ScanRules(exclude_patterns=[1, 2])
