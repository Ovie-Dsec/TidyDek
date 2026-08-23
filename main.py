"""TidyDek application entry point.

Composition root and boot order (order matters):
1. structured JSON logging (everything after this is observable)
2. per-monitor DPI awareness BEFORE any window exists
3. crash hooks (sys, threading, and later the Tk bridge)
4. settings load -> theme -> scan rules
5. Model / ViewModels / View wiring + system tray + updater menu

Run with: py main.py
"""

import os
import sys
import tempfile
import threading
from pathlib import Path

if not sys.platform.startswith("win"):
    raise SystemExit("TidyDek currently supports Windows only.")

from src.core.logsetup import get_logger, setup_logging  # noqa: E402

LOG_FILE = setup_logging()
_logger = get_logger("app")
_logger.info("boot starting")

# --- DPI before ANY Tk/window creation --------------------------------------
import ctypes  # noqa: E402


def _enable_per_monitor_dpi() -> None:
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == -4
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4)
        ):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_per_monitor_dpi()

# --- crash telemetry ----------------------------------------------------------
from src.integrations import win32_api  # noqa: E402
from src.integrations.crash_reporter import install_crash_hooks  # noqa: E402

CRASH_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TidyDek" / "crash"
crash_handle = install_crash_hooks(CRASH_DIR, logs_dir=LOG_FILE.parent)

# --- application imports -------------------------------------------------------
import customtkinter as ctk  # noqa: E402

from src.core.config import ConfigManager  # noqa: E402
from src.core.config_schema import ScanRules  # noqa: E402
from src.core.state import StateStore  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.gui.settings_dialog import SettingsDialog  # noqa: E402
from src.integrations.crash_reporter import confirm  # noqa: E402
from src.integrations.system_tray import SystemTrayIcon  # noqa: E402
from src.integrations.updater import UpdateError, Updater  # noqa: E402
from src.version import APP_NAME, VERSION  # noqa: E402
from src.viewmodels.app_viewmodel import AppViewModel  # noqa: E402
from src.viewmodels.settings_viewmodel import (  # noqa: E402
    SettingsViewModel,
    default_config_path,
)


def _bundled_asset(name: str) -> Path | None:
    """Resolve an asset both frozen (PyInstaller _MEIPASS) and from source."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    candidate = base / "assets" / name
    return candidate if candidate.is_file() else None


def main() -> None:
    ctk.set_default_color_theme("blue")

    config = ConfigManager(default_config_path())
    boot_settings = SettingsViewModel(config_manager=config)
    working = boot_settings.snapshot()["working"]
    ctk.set_appearance_mode(working["general"]["theme"])

    try:
        scan_rules = ScanRules(**working.get("scan_rules", {}))
    except Exception as exc:
        _logger.warning("invalid scan rules in settings; defaults used: %r", exc)
        scan_rules = ScanRules()

    store = StateStore()
    view_model = AppViewModel(store, scan_rules=scan_rules)
    window = MainWindow(view_model)
    window.title(f"{APP_NAME} v{VERSION}")

    # Taskbar progress capability injected post-construction (the bridge
    # resolves the HWND lazily, so ordering here is safe).
    from src.integrations.taskbar import TaskbarProgress

    window.attach_taskbar(TaskbarProgress(lambda: int(window.winfo_id())))

    icon_asset = _bundled_asset("icon.ico")
    if icon_asset is not None:
        try:
            window.iconbitmap(str(icon_asset))
        except Exception:
            pass  # cosmetic only; default icon remains

    tray: list[SystemTrayIcon] = []
    settings_dialog: list[SettingsDialog] = []
    tray_prefix = f"{APP_NAME} v{VERSION}"

    def perform_teardown() -> None:
        """Idempotent shutdown shared by Quit, tray updates, titlebar close."""
        if settings_dialog:
            dlg = settings_dialog[0]
            if dlg.winfo_exists():
                dlg.close_dialog()
        if tray:
            tray[0].close()
        window._on_close()

    def apply_saved_theme(snapshot) -> None:
        theme = snapshot["working"]["general"]["theme"]
        window.after(0, lambda: ctk.set_appearance_mode(theme))

    def open_settings() -> None:
        existing = settings_dialog[0] if settings_dialog else None
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_set()
            return
        vm = SettingsViewModel(
            config_manager=config, on_applied=apply_saved_theme
        )
        settings_dialog.clear()
        settings_dialog.append(SettingsDialog(window, vm))

    def show_main_from_tray() -> None:
        def restore():
            window.deiconify()
            window.lift()
            window.focus_force()
            window.attributes("-topmost", True)
            window.after(50, lambda: window.attributes("-topmost", False))

        window.after(0, restore)

    updater = Updater(
        current_version=VERSION,
        manifest_url=os.environ.get(
            "TIDYDEK_UPDATE_URL",
            "https://updates.tidydek.com/latest.json",
        ),
    )

    def check_for_updates_async() -> None:
        """Runs off the UI thread; dialogs marshal back via window.after."""

        def ask_on_ui(question: str, timeout: float = 600.0) -> bool:
            """Ask a yes/no on the Tk thread; block this worker for the answer."""
            answer = {"value": False}
            done = threading.Event()

            def prompt():
                try:
                    answer["value"] = confirm(question, "TidyDek Updates")
                finally:
                    done.set()

            window.after(0, prompt)
            if not done.wait(timeout):
                return False  # user absent or UI stuck: never auto-install
            return answer["value"]

        def worker():
            try:
                available, manifest, message = updater.check()
                if not available or manifest is None:
                    window.after(0, lambda: win32_api.show_message_box(
                        "TidyDek Updates", message,
                        icon=win32_api.MB_ICONINFORMATION))
                    return

                target = Path(tempfile.gettempdir()) / (
                    f"TidyDek-setup-{manifest.version}.exe"
                )
                path = updater.download(manifest, target)
                question = (
                    f"{message}\n\n"
                    f"Release notes: {manifest.release_notes}\n\n"
                    "Install now? TidyDek will close and restart."
                )
                if not ask_on_ui(question):
                    _logger.info("update deferred by user")
                    return
                updater.install(path)
                window.after(0, perform_teardown)
                os._exit(0)  # silent handoff: the installer owns the machine now
            except UpdateError as exc:
                _logger.error("update flow failed: %s", exc)
                window.after(0, lambda: win32_api.show_message_box(
                    "TidyDek Updates", f"Update failed:\n{exc}",
                    icon=win32_api.MB_ICONERROR))
            except Exception as exc:  # never let the thread die silently
                _logger.exception("unexpected update-thread error")
                sys.stderr.write(f"update thread error: {exc!r}\n")

        threading.Thread(target=worker, name="TidyDekUpdate", daemon=True).start()

    def quit_from_tray() -> None:
        window.after(0, perform_teardown)

    def close_from_titlebar() -> None:
        perform_teardown()

    def dispatch_menu(command_key: str) -> None:
        handlers = {
            "show": show_main_from_tray,
            "settings": lambda: window.after(0, open_settings),
            "update": lambda: window.after(0, check_for_updates_async),
            "quit": quit_from_tray,
        }
        handler = handlers.get(command_key)
        if handler is not None:
            handler()

    tray.append(
        SystemTrayIcon(
            tooltip=tray_prefix,
            icon_path=icon_asset,
            menu_items=(
                ("Show TidyDek", "show"),
                ("Settings...", "settings"),
                ("Check for Updates...", "update"),
                ("", "sep"),
                ("Quit", "quit"),
            ),
            on_menu=dispatch_menu,
            on_activate=show_main_from_tray,
        )
    )
    if not tray[0].add():
        _logger.warning("tray icon unavailable; continuing without it")

    window.protocol("WM_DELETE_WINDOW", close_from_titlebar)

    # Bridge the THIRD hook surface: exceptions inside Tk callbacks bypass
    # sys.excepthook entirely; route them into the crash reporter instead.
    MainWindow.report_callback_exception = (
        lambda self, exc_type, exc_value, exc_tb: crash_handle(
            exc_type, exc_value, exc_tb, "TkCallback"
        )
    )

    def sync_tooltip(snapshot, keys) -> None:
        if tray and tray[0].window.hwnd:
            tray[0].update_tooltip(f"{tray_prefix} - {snapshot['status']}")

    store.subscribe(sync_tooltip)

    try:
        window.mainloop()
    finally:
        if tray:
            tray[0].close()
        _logger.info("boot finished (window closed)")


if __name__ == "__main__":
    main()
