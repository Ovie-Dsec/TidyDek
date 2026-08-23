"""Unit tests for secure JSON/YAML/TOML configuration persistence."""

import pytest

from src.core.config import ConfigError, ConfigManager
from src.core import config as config_module

SAMPLE = {"app": {"name": "TidyDek", "threads": 4}, "features": {"tray": True}}


@pytest.mark.parametrize("ext", [".json", ".yaml", ".toml"])
def test_round_trip_all_formats(tmp_path, ext):
    cfg = ConfigManager(tmp_path / f"conf{ext}")
    cfg.save(SAMPLE)
    assert cfg.load() == SAMPLE


def test_yml_alias_extension(tmp_path):
    cfg = ConfigManager(tmp_path / "conf.yml")
    cfg.save({"k": "v"})
    assert cfg.load() == {"k": "v"}


def test_unsupported_extension_rejected(tmp_path):
    cfg = ConfigManager(tmp_path / "conf.ini")
    with pytest.raises(ConfigError):
        cfg.load()


def test_missing_file_raises_file_not_found(tmp_path):
    cfg = ConfigManager(tmp_path / "absent.json")
    with pytest.raises(FileNotFoundError):
        cfg.load()


def test_malformed_yaml_raises_config_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("key: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError):
        ConfigManager(path).load()


def test_non_mapping_root_rejected(tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ConfigError):
        ConfigManager(path).load()


def test_oversized_file_rejected(tmp_path, monkeypatch):
    path = tmp_path / "big.json"
    path.write_text("{}", encoding="utf-8")  # 2 bytes on disk
    monkeypatch.setattr(config_module, "MAX_CONFIG_BYTES", 1)
    with pytest.raises(ConfigError):
        ConfigManager(path).load()


def test_atomic_save_leaves_no_temp_files_behind(tmp_path):
    cfg = ConfigManager(tmp_path / "conf.json")
    cfg.save({"a": 1})
    leftovers = [entry for entry in tmp_path.iterdir() if entry.name != "conf.json"]
    assert leftovers == []


def test_save_creates_missing_parent_directories(tmp_path):
    cfg = ConfigManager(tmp_path / "sub" / "dir" / "conf.yaml")
    cfg.save({"ok": True})
    assert cfg.load() == {"ok": True}


def test_toml_cannot_store_none(tmp_path):
    cfg = ConfigManager(tmp_path / "conf.toml")
    with pytest.raises(ConfigError):
        cfg.save({"bad": None})


def test_save_requires_mapping_root(tmp_path):
    cfg = ConfigManager(tmp_path / "conf.json")
    with pytest.raises(ConfigError):
        cfg.save(["not", "a", "dict"])  # type: ignore[arg-type]
