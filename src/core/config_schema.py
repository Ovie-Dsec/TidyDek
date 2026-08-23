"""Typed configuration schema for scanning rules (Phase 8).

Single schema shared by the settings store and the scanner: settings persist
plain dicts shaped exactly like these models; validation happens when a
ScanRules is instantiated from persisted data, so malformed saved values can
never reach the engine.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ScanRules(BaseModel):
    """Filtering rules for :class:`src.core.scanner.FilteredScanner`."""

    model_config = ConfigDict(extra="ignore")

    # Gitignore-style glob patterns for directory/file exclusion,
    # e.g. "**/__pycache__", "*.tmp", "node_modules/"
    exclude_patterns: list[str] = Field(default_factory=list)

    # Gitignore-style glob patterns restricting which FILES are reported.
    # Default reports everything.
    include_patterns: list[str] = Field(
        default_factory=lambda: ["**/*"]
    )

    # Maximum directory nesting below the root; prunes descent, guarding
    # against pathological trees.
    max_depth: int = Field(default=10, ge=1, le=64)


class AppConfig(BaseModel):
    """Top-level application configuration container."""

    model_config = ConfigDict(extra="ignore")

    scan_rules: ScanRules = Field(default_factory=ScanRules)
