"""Secure configuration persistence for JSON / YAML / TOML.

Security posture:
- Parsing uses non-executing loaders only (``json``, ``yaml.safe_load``,
  ``tomllib``/``tomli``). Arbitrary object construction is impossible.
- File size is capped to mitigate resource-exhaustion attacks.
- Writes are atomic (temp file in the target directory + ``os.replace``),
  UTF-8 encoded with sorted keys, producing deterministic, diff-friendly files.
- The configuration root must always be a mapping (dict).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

import yaml

try:  # Python 3.11+: stdlib TOML reader
    import tomllib as _toml_reader
except ModuleNotFoundError:  # Python 3.10: pinned backport
    import tomli as _toml_reader  # type: ignore[no-redef]

import tomli_w

MAX_CONFIG_BYTES = 8 * 1024 * 1024  # 8 MiB hard cap on config file size

_TEXT_FORMAT_LOADERS: dict[str, Callable[[str], Any]] = {
    ".json": json.loads,
    ".yaml": yaml.safe_load,
    ".yml": yaml.safe_load,
}
_TOML_SUFFIXES = {".toml"}
SUPPORTED_EXTENSIONS = frozenset(_TEXT_FORMAT_LOADERS) | _TOML_SUFFIXES


class ConfigError(Exception):
    """Raised when a configuration file cannot be parsed or written."""


class ConfigManager:
    """Read and atomically write a single configuration file."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    # -------------------------------------------------------------- load
    def load(self) -> dict[str, Any]:
        suffix = self.path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ConfigError(f"Unsupported config format: {suffix!r}")
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise ConfigError(f"Cannot read config file: {self.path}") from exc
        if len(raw) > MAX_CONFIG_BYTES:
            raise ConfigError("Configuration file exceeds size limit")
        data = self._parse(suffix, raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ConfigError("Configuration root must be a mapping")
        return data

    @staticmethod
    def _parse(suffix: str, text: str) -> Any:
        try:
            if suffix in _TOML_SUFFIXES:
                return _toml_reader.loads(text)
            return _TEXT_FORMAT_LOADERS[suffix](text)
        except (ValueError, yaml.YAMLError) as exc:
            raise ConfigError(f"Malformed {suffix} configuration") from exc

    # -------------------------------------------------------------- save
    def save(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise ConfigError("Configuration root must be a mapping")
        suffix = self.path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ConfigError(f"Unsupported config format: {suffix!r}")
        text = self._serialize(suffix, data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=self.path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except OSError as exc:
            raise ConfigError(f"Cannot write config file: {self.path}") from exc
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass

    @staticmethod
    def _serialize(suffix: str, data: dict[str, Any]) -> str:
        try:
            if suffix == ".json":
                return json.dumps(
                    data, ensure_ascii=False, indent=2, sort_keys=True
                ) + "\n"
            if suffix in (".yaml", ".yml"):
                return yaml.safe_dump(
                    data,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=True,
                )
            return tomli_w.dumps(data)
        except (TypeError, ValueError, yaml.YAMLError) as exc:
            raise ConfigError(
                f"Value not serializable as {suffix}: {exc}"
            ) from exc
