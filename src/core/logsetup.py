"""Structured JSON logging with rotation and a per-session trace id.

Every record is a single JSON line:
    {"ts": "...", "level": "INFO", "logger": "tidydek.app",
     "session": "<uuid4-hex>", "message": "...", ["traceback": "..."]}

Design notes:
- Handler attaches to the ``tidydek`` root logger; child loggers come from
  :func:`get_logger`. Setup is idempotent (re-invocation replaces handlers),
  which keeps tests and repeated boots clean.
- Rotation defaults: 5 MiB per file, 3 backups, so disk use is bounded.
- Session id is generated once per process; every line carries it so support
  can correlate all records from one user session.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SESSION_ID = uuid.uuid4().hex
LOGGER_ROOT = "tidydek"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUPS = 3


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "session": SESSION_ID,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def default_log_dir() -> Path:
    import os

    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "TidyDek" / "logs"


def setup_logging(
    directory: Optional[Path] = None,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backups: int = DEFAULT_BACKUPS,
    level: int = logging.INFO,
) -> Path:
    """Configure the tidydek logger; returns the active log file path."""
    target_dir = directory if directory is not None else default_log_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    log_file = target_dir / "tidydek.log"

    from logging.handlers import RotatingFileHandler

    logger = logging.getLogger(LOGGER_ROOT)
    logger.setLevel(level)
    logger.propagate = False
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        existing.close()

    handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
    )
    handler.setFormatter(JsonLineFormatter())
    logger.addHandler(handler)
    return log_file


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_ROOT}.{name}")


def get_session_id() -> str:
    return SESSION_ID
