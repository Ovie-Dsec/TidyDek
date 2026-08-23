"""Crash telemetry: report writing, hook coverage, clean non-zero exit."""

import json
import sys
import threading
from urllib.parse import quote

from src.core.logsetup import setup_logging
from src.integrations.crash_reporter import install_crash_hooks


def _install(tmp_path, exit_log):
    setup_logging(tmp_path / "logs")
    return install_crash_hooks(
        tmp_path / "crash", show_dialog=False,
        exit_fn=lambda code: exit_log.append(code),
    )


def _last_log_entry(tmp_path):
    log_file = tmp_path / "logs" / "tidydek.log"
    lines = [line for line in log_file.read_text(encoding="utf-8").splitlines() if line]
    return json.loads(lines[-1])


def test_direct_invocation_writes_report_logs_and_exits_nonzero(tmp_path):
    exits = []
    handle = _install(tmp_path, exits)

    try:
        raise ValueError("synthetic UI explosion")
    except ValueError:
        handle(*sys.exc_info(), thread_label="TkCallback")

    reports = list((tmp_path / "crash").glob("CRASH_REPORT_*.txt"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "ValueError" in text and "synthetic UI explosion" in text
    assert "send this file to support" in text.lower()

    entry = _last_log_entry(tmp_path)
    assert entry["level"] == "ERROR"
    assert "ValueError" in entry["traceback"]
    assert exits == [1]


def test_threading_excepthook_captures_worker_crashes(tmp_path):
    exits = []
    handle = _install(tmp_path, exits)
    original_hook = threading.excepthook
    try:
        # install_crash_hooks already set threading.excepthook; trigger it via
        # a real crashing daemon thread and wait for the report to appear.
        def worker():
            raise KeyError("thread boom")

        thread = threading.Thread(target=worker, name="CrashProbe")
        thread.start()
        thread.join(5)
        deadline_checks = 50
        while not list((tmp_path / "crash").glob("*.txt")) and deadline_checks:
            deadline_checks -= 1
            threading.Event().wait(0.05)
    finally:
        threading.excepthook = original_hook

    reports = list((tmp_path / "crash").glob("CRASH_REPORT_*.txt"))
    assert reports, "worker crash produced no report"
    assert "KeyError" in reports[0].read_text(encoding="utf-8")


def test_tk_bridge_routes_callback_exceptions(tmp_path):
    exits = []
    handle = _install(tmp_path, exits)

    # The production bridge is:
    #   MainWindow.report_callback_exception = (
    #       lambda self, et, ev, tb: crash_handle(et, ev, tb, "TkCallback"))
    # so self never reaches the handler; simulate exactly that call.
    try:
        raise ZeroDivisionError("tk callback division")
    except ZeroDivisionError:
        handle(*sys.exc_info(), thread_label="TkCallback")

    reports = list((tmp_path / "crash").glob("*.txt"))
    assert reports
    text = reports[0].read_text(encoding="utf-8")
    assert "ZeroDivisionError" in text and "TkCallback" in text
    assert exits == [1]


def test_report_includes_session_id(tmp_path):
    exits = []
    handle = _install(tmp_path, exits)
    from src.core.logsetup import get_session_id

    try:
        raise OSError("disk hiccup")
    except OSError:
        handle(*sys.exc_info())
    report_text = next(iter((tmp_path / "crash").glob("*.txt"))).read_text(
        encoding="utf-8"
    )
    assert get_session_id()[:8] in report_text or get_session_id() in report_text


# ------------------------------------------------- telemetry closure (Ph.15)
def test_send_report_packages_zip_and_opens_mail(tmp_path, monkeypatch):
    import zipfile

    from src.integrations import crash_reporter as cr

    opened = []
    monkeypatch.setattr(cr, "show_message_box", lambda *a, **k: cr.IDYES)
    monkeypatch.setattr(cr, "_startfile", lambda url: opened.append(url))

    setup_logging(tmp_path / "logs")
    exits = []
    handle = install_crash_hooks(
        tmp_path / "crash", logs_dir=tmp_path / "logs",
        show_dialog=True, exit_fn=lambda code: exits.append(code),
    )
    try:
        raise ValueError("packaging probe")
    except ValueError:
        handle(*sys.exc_info())

    archives = list((tmp_path / "crash").parent.glob("TidyDek_diagnostics_*.zip"))
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as bundle:
        names = bundle.namelist()
    assert any(name.startswith("CRASH_REPORT_") for name in names)
    assert any("tidydek.log" in name for name in names)

    assert len(opened) == 1
    assert opened[0].startswith("mailto:support@tidydek.com")
    assert "subject=" in opened[0]
    # The zip path must be percent-encoded inside the mailto body.
    zip_name = archives[0].name
    assert quote(zip_path_str := str(archives[0]), safe="") in opened[0] or \
        quote(zip_name) in opened[0]

    assert exits == [1]


def test_declining_send_skips_packaging_and_mail(tmp_path, monkeypatch):
    from src.integrations import crash_reporter as cr

    opened = []
    monkeypatch.setattr(cr, "show_message_box", lambda *a, **k: 7)  # IDNO=7
    monkeypatch.setattr(cr, "_startfile", lambda url: opened.append(url))

    setup_logging(tmp_path / "logs")
    exits = []
    handle = install_crash_hooks(
        tmp_path / "crash", logs_dir=tmp_path / "logs",
        show_dialog=True, exit_fn=lambda code: exits.append(code),
    )
    try:
        raise OSError("declined probe")
    except OSError:
        handle(*sys.exc_info())

    assert not list((tmp_path / "crash").parent.glob("TidyDek_diagnostics_*.zip"))
    assert opened == []
    assert exits == [1]
