"""Headless plugin contract: the ONLY surface v2.1 plugins may rely on.

Isolation guarantees (mechanically enforced by tests/test_plugin_contract.py
and the architecture suite):
- This module must not import GUI toolkits, raw FFI modules, or the OS
  integration layer; plugins written against it stay portable to headless
  contexts by construction.
- All event payloads are frozen dataclasses; rule snapshots are exposed as
  read-only mappings. A plugin cannot mutate engine state through the
  contract.

Dispatch/runtime loading is deliberately NOT part of this module; v2.1 will
add a separate loader that consumes these types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

PLUGIN_API_VERSION = "1"


@dataclass(frozen=True)
class FileEvent:
    """Read-only snapshot of one file discovered during a scan."""

    path: str
    name: str
    extension: str
    size: int


@dataclass(frozen=True)
class ScanSummary:
    """Read-only terminal summary of a completed scan."""

    root: str
    files_scanned: int
    cancelled: bool


@runtime_checkable
class PluginContext(Protocol):
    """Structural contract every TidyDek plugin must satisfy.

    ``scan_rules`` is an immutable mapping view of the active ScanRules;
    ``emit_log`` routes plugin messages into the structured telemetry stream
    without granting access to log files or handlers.
    """

    scan_rules: Mapping[str, Any]

    def emit_log(self, level: str, message: str) -> None:
        ...

    def on_file(self, event: FileEvent) -> None:
        ...

    def on_scan_complete(self, summary: ScanSummary) -> None:
        ...
