"""Crash telemetry: capture fatal exceptions, persist a report, offer handoff.

Hook coverage (all three are required; any single one leaves a silent path):
- ``sys.excepthook``          -> uncaught exceptions on the main thread
- ``threading.excepthook``    -> uncaught exceptions in worker threads
- Tk ``report_callback_exception`` -> exceptions inside Tkinter callbacks,
  which BYPASS sys.excepthook entirely. The composition root bridges this by
  assigning MainWindow.report_callback_exception to :func:`handle_tk_exception`.

Behavior on a fatal: JSON-log the full traceback, write a friendly
CRASH_REPORT_<session>.txt under %LOCALAPPDATA%\\TidyDek\\crash, then ask the
user (native Yes/No box) whether to package diagnostics. On Yes: logs and
crash artifacts are zipped next to the report, the default mail client opens
with a pre-filled subject and the zip path in the body, and the app exits.
Lives in the integrations layer because it touches win32_api directly.
"""

from __future__ import annotations

import os
import sys
import threading
import traceback
import zipfile
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

from src.core.logsetup import get_logger, get_session_id

from .win32_api import (
    IDYES,
    MB_ICONERROR,
    MB_YESNO,
    show_message_box,
)

ExitFn = Callable[[int], None]
SUPPORT_EMAIL = "support@tidydek.com"
_startfile = os.startfile  # module-level seam for test monkeypatching
_logger = get_logger("crash")


def _write_report(report_dir: Path, exc_text: str, thread_label: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    report = report_dir / f"CRASH_REPORT_{get_session_id()[:8]}.txt"
    body = (
        "TidyDek encountered an unexpected problem and had to close.\n"
        "\n"
        f"Session id : {get_session_id()}\n"
        f"Thread     : {thread_label}\n"
        "\n"
        "Please send this file to support so we can fix the cause.\n"
        "\n"
        "---------------- technical details ----------------\n"
        f"{exc_text}\n"
    )
    report.write_text(body, encoding="utf-8")
    return report


def _package_diagnostics(
    report_dir: Optional[Path],
    logs_dir: Optional[Path],
) -> Optional[Path]:
    """Zip crash reports + recent logs; returns the archive path or None."""
    base = report_dir.parent if report_dir else Path.cwd()
    zip_path = base / f"TidyDek_diagnostics_{get_session_id()[:8]}.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as bundle:
            for directory in (report_dir, logs_dir):
                if directory is None or not directory.is_dir():
                    continue
                for file in sorted(directory.rglob("*")):
                    if file.is_file():
                        bundle.write(file, file.name)
        return zip_path if zip_path.stat().st_size > 0 else None
    except OSError as exc:
        _logger.warning("diagnostics packaging failed: %s", exc)
        return None


def _open_mail_client(zip_path: Path) -> None:
    body = (
        "TidyDek crashed unexpectedly. "
        f"The diagnostic archive is attached at:\n{zip_path}\n\n"
        "Please attach it to this email before sending."
    )
    url = (
        f"mailto:{SUPPORT_EMAIL}"
        "?subject=" + quote("TidyDek Crash Report")
        + "&body=" + quote(body)
    )
    try:
        _startfile(url)
    except OSError as exc:
        _logger.warning("could not open mail client: %s", exc)


def install_crash_hooks(
    report_dir: Path,
    *,
    logs_dir: Optional[Path] = None,
    show_dialog: bool = True,
    exit_fn: ExitFn = os._exit,
) -> Callable[..., None]:
    """Install all exception hooks; returns the raw handler for tests/bridges."""

    def handle(
        exc_type=None,
        exc_value=None,
        exc_tb=None,
        thread_label: str = "MainThread",
    ) -> None:
        try:
            exc_text = "".join(
                traceback.format_exception(exc_type, exc_value, exc_tb)
            )
            _logger.error(
                "Unhandled exception on %s", thread_label,
                exc_info=(exc_type, exc_value, exc_tb),
            )
            report = _write_report(Path(report_dir), exc_text, thread_label)
            if show_dialog:
                wants_send = (
                    show_message_box(
                        "TidyDek has stopped",
                        "An unexpected problem forced TidyDek to close.\n\n"
                        f"A crash report was saved to:\n{report}\n\n"
                        "Package diagnostics and open your email client "
                        "to send them to support?",
                        icon=MB_ICONERROR,
                        buttons=MB_YESNO,
                    )
                    == IDYES
                )
                if wants_send:
                    archive = _package_diagnostics(
                        Path(report_dir),
                        Path(logs_dir) if logs_dir else None,
                    )
                    if archive is not None:
                        _open_mail_client(archive)
                    else:
                        show_message_box(
                            "TidyDek",
                            "Diagnostics could not be packaged.\n"
                            f"Please send this file manually:\n{report}",
                            icon=MB_ICONERROR,
                        )
        finally:
            exit_fn(1)

    def sys_hook(exc_type, exc_value, exc_tb) -> None:
        handle(exc_type, exc_value, exc_tb, "MainThread")

    def threading_hook(args: threading.ExceptHookArgs) -> None:
        label = f"Thread-{args.thread.name if args.thread else 'unknown'}"
        handle(args.exc_type, args.exc_value, args.exc_traceback, label)

    def handle_tk_exception(_self=None, exc_type=None, exc_value=None,
                            exc_tb=None) -> None:
        """Bridge target for Tk's report_callback_exception."""
        if exc_type is None:  # direct call style used in tests
            return
        handle(exc_type, exc_value, exc_tb, "TkCallback")

    sys.excepthook = sys_hook
    threading.excepthook = threading_hook
    return handle


def confirm(message: str, title: str = "TidyDek") -> bool:
    return show_message_box(title, message, buttons=MB_YESNO) == IDYES
