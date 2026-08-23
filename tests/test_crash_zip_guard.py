"""Phase 19.1: zip-bomb guard — packaged diagnostics are tail-capped."""

import zipfile

from src.core.logsetup import setup_logging
from src.integrations.crash_reporter import (
    MAX_LOG_BYTES_PER_FILE,
    _package_diagnostics,
)

TEN_MB = 10 * 1024 * 1024


def test_ten_mb_log_is_tailed_below_3mb_archive(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    log_file = setup_logging(logs_dir)  # real handler owns tidydek.log
    for handler in __import__("logging").getLogger("tidydek").handlers:
        handler.close()

    # Hostile-scale dummy log, far beyond the per-file guard.
    line = "2026-01-01 WARN padding x" + "y" * 120 + "\n"
    with log_file.open("w", encoding="utf-8") as fh:
        while log_file.stat().st_size < TEN_MB:
            fh.write(line)
        fh.write("SENTINEL-TAIL-RECORD\n")

    crash_dir = tmp_path / "crash"
    crash_dir.mkdir()
    (crash_dir / "CRASH_REPORT_probe.txt").write_text(
        "boom", encoding="utf-8"
    )

    archive = _package_diagnostics(crash_dir, logs_dir)
    assert archive is not None
    size = archive.stat().st_size
    assert size < 3 * 1024 * 1024, f"archive too large: {size}"

    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert any(name.startswith("CRASH_REPORT_") for name in names)
        entry = bundle.getinfo(log_file.name)
        # Decompressed payload must respect the per-file cap (small slack for
        # the forward-trim to a line boundary).
        assert entry.file_size <= MAX_LOG_BYTES_PER_FILE + 256
        tail_text = bundle.read(log_file.name).decode("utf-8", "replace")
    assert "SENTINEL-TAIL-RECORD" in tail_text, "tail must retain latest data"


def test_small_logs_pass_through_untruncated(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    small = logs_dir / "tidydek.log"
    small.write_text("HEAD-MARKER\nmiddle\nTAIL-MARKER\n", encoding="utf-8")

    archive = _package_diagnostics(None, logs_dir)
    assert archive is not None
    with zipfile.ZipFile(archive) as bundle:
        content = bundle.read("tidydek.log").decode("utf-8")
    assert "HEAD-MARKER" in content and "TAIL-MARKER" in content
