"""SystemTrayIcon tests: menu table logic, focus ordering contract, real cycle.

The focus-ordering test proves the KB135788 requirement mechanically:
SetForegroundWindow strictly BEFORE TrackPopupMenuEx, WM_NULL posted after.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="Windows-only integration"
)

from src.integrations import system_tray as st
from src.integrations import win32_api as w
from src.integrations.system_tray import SystemTrayIcon
from types import SimpleNamespace


def _bare_tray(menu_items, on_menu=None):
    """Bypass __init__ to unit-test menu/focus logic without shell side effects."""
    tray = SystemTrayIcon.__new__(SystemTrayIcon)
    tray._menu_items = tuple(menu_items)
    tray._on_menu = on_menu
    tray._tooltip = "t"
    tray._hicon = None
    tray._added = False
    return tray


def test_populate_menu_assigns_ids_and_skips_separators(monkeypatch):
    calls = []
    monkeypatch.setattr(st, "_AppendMenuW", lambda m, f, i, s: calls.append((m, f, i, s)) or True)
    tray = _bare_tray((("Show", "show"), ("", "sep"), ("Quit", "quit")))
    mapping = tray._populate_menu(999)
    assert calls == [
        (999, w.MF_STRING, 100, "Show"),
        (999, w.MF_SEPARATOR, 0, None),
        (999, w.MF_STRING, 101, "Quit"),
    ]
    assert mapping == {100: "show", 101: "quit"}


def test_focus_order_setforeground_before_track_then_wm_null(monkeypatch):
    order = []
    monkeypatch.setattr(st, "_CreatePopupMenu", lambda: 4242)
    monkeypatch.setattr(st, "_AppendMenuW", lambda m, f, i, s: True)
    monkeypatch.setattr(st, "_GetCursorPos", lambda ref: True)
    monkeypatch.setattr(st, "_DestroyMenu", lambda m: order.append("destroy") or True)
    monkeypatch.setattr(st, "_PostMessageW",
                        lambda h, msg, wp, lp: order.append(("post", msg)) or True)
    monkeypatch.setattr(st, "_SetForegroundWindow",
                        lambda h: order.append("set_fg") or True)

    def fake_track(menu, flags, x, y, hwnd, params):
        order.append("track")
        assert flags & w.TPM_RETURNCMD, "RETURNCMD required for direct dispatch"
        return 101  # -> "quit"

    monkeypatch.setattr(st, "_TrackPopupMenuEx", fake_track)

    selected = []
    tray = _bare_tray((("Show", "show"), ("Quit", "quit")),
                      on_menu=selected.append)
    tray._window = SimpleNamespace(hwnd=55)  # type: ignore[assignment]

    tray.show_menu()

    assert order[0] == "set_fg", "KB135788 violation: foreground not set first"
    assert order[1] == "track"
    assert ("post", w.WM_NULL) in order, "WM_NULL must follow the popup"
    assert selected == ["quit"]


def test_show_menu_survives_zero_menu_handle(monkeypatch):
    monkeypatch.setattr(st, "_CreatePopupMenu", lambda: 0)
    tray = _bare_tray((("Quit", "quit"),))
    tray.show_menu()  # must not raise


def test_real_shell_add_modify_remove_cycle():
    fired = []
    with SystemTrayIcon(
        tooltip="TidyDek test",
        menu_items=(("Ping", "ping"),),
        on_menu=fired.append,
    ) as tray:
        if not tray.add():
            pytest.skip("shell notification area unavailable in this session")
        assert tray.update_tooltip("TidyDek test 2") is True
    # __exit__ performed remove()+close(); icon gone, pump joined.
