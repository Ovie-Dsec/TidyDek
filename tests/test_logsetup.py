"""Structured JSON logging: format, session traceability, rotation."""

import json
import logging

from src.core.logsetup import get_logger, get_session_id, setup_logging


def _read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_records_are_single_line_json_with_core_fields(tmp_path):
    log_file = setup_logging(tmp_path)
    logger = get_logger("probe")
    logger.info("hello %s", "world")
    for handler in logging.getLogger("tidydek").handlers:
        handler.flush()
    entries = _read_lines(log_file)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["level"] == "INFO"
    assert entry["logger"] == "tidydek.probe"
    assert entry["message"] == "hello world"
    assert entry["session"] == get_session_id()
    assert "T" in entry["ts"]  # ISO timestamp


def test_session_id_is_stable_across_calls():
    assert get_session_id() == get_session_id()


def test_traceback_attached_for_errors(tmp_path):
    log_file = setup_logging(tmp_path)
    logger = get_logger("boom")
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        logger.exception("caught during test")
    for handler in logging.getLogger("tidydek").handlers:
        handler.flush()
    entry = _read_lines(log_file)[-1]
    assert entry["level"] == "ERROR"
    assert "RuntimeError: kaboom" in entry["traceback"]


def test_rotation_creates_backup_and_bounds_disk_use(tmp_path):
    tiny = 512
    log_file = setup_logging(tmp_path, max_bytes=tiny, backups=2)
    logger = get_logger("chatty")
    filler = "x" * 200
    for index in range(10):
        logger.info("%d %s", index, filler)
    for handler in logging.getLogger("tidydek").handlers:
        handler.flush()

    backups = list(tmp_path.glob("tidydek.log.*"))
    assert backups, "rotation never triggered"
    assert len(backups) <= 2
    active_size = log_file.stat().st_size
    assert active_size <= tiny * 2


def test_setup_is_idempotent_no_duplicate_handlers(tmp_path):
    setup_logging(tmp_path)
    setup_logging(tmp_path)
    handlers = logging.getLogger("tidydek").handlers
    assert len(handlers) == 1
