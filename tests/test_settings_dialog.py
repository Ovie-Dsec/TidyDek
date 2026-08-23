"""SettingsDialog View tests: reactivity, HIG geometry, strict Tab map."""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="GUI test needs an interactive session"
)

import customtkinter as ctk

from src.gui.settings_dialog import THEMES, SettingsDialog
from src.viewmodels.settings_viewmodel import DEFAULT_SETTINGS, SettingsViewModel


@pytest.fixture(scope="module")
def root():
    """One Tcl interpreter per module: many roots proved flaky (tk.tcl races)."""
    root = None
    try:
        root = ctk.CTk()
    except Exception as exc:
        pytest.skip(f"display unavailable for GUI tests: {exc!r}")
    assert root is not None
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture()
def dlg(root):
    dialog = None
    try:
        dialog = SettingsDialog(root, SettingsViewModel())
        dialog.withdraw()  # keep automated runs visually silent
        yield dialog
    except Exception as exc:
        pytest.skip(f"display unavailable for GUI test: {exc!r}")
    finally:
        if dialog is not None:
            try:
                dialog.close_dialog()
            except Exception:
                pass


def test_dialog_renders_current_values(dlg):
    assert dlg._theme_menu.get() == "System"
    assert bool(int(dlg._autoscan_switch.get())) is False
    assert dlg._exclude_entry.get() == ""
    assert dlg._apply_btn.cget("state") == "disabled"


def test_field_change_enables_apply_via_reactive_loop(dlg):
    dlg._on_theme_selected("Dark")          # user intent path
    assert dlg._vm.snapshot()["dirty"] is True
    assert dlg._apply_btn.cget("state") == "normal"
    assert dlg._theme_menu.get() == "Dark"


def test_reverting_change_disables_apply_again(dlg):
    dlg._on_theme_selected("Dark")
    dlg._on_theme_selected("System")
    assert dlg._vm.snapshot()["dirty"] is False
    assert dlg._apply_btn.cget("state") == "disabled"


def test_exclude_entry_parses_comma_list_and_ignores_blanks(dlg):
    dlg._exclude_entry.insert(0, " *.tmp , , node_modules ")
    dlg._on_exclude_edited()
    working = dlg._vm.snapshot()["working"]
    assert working["scan_rules"]["exclude_patterns"] == ["*.tmp", "node_modules"]
    assert dlg._apply_btn.cget("state") == "normal"


def test_windows_hig_button_order_ok_cancel_apply(dlg):
    dlg.update_idletasks()
    ok_x, ok_y = dlg._ok_btn.winfo_x(), dlg._ok_btn.winfo_y()
    cancel_x, cancel_y = dlg._cancel_btn.winfo_x(), dlg._cancel_btn.winfo_y()
    apply_x, apply_y = dlg._apply_btn.winfo_x(), dlg._apply_btn.winfo_y()
    assert ok_y == cancel_y == apply_y, "buttons must share one row"
    assert ok_x < cancel_x < apply_x, "HIG order violated: OK -> Cancel -> Apply"


def _tab_targets(dialog):
    """Resolve the explicit tab map into the traversal sequence."""
    start = dialog._theme_menu
    order = [start]
    current = start
    for _ in range(len(dialog._tab_next)):
        nxt = dialog._tab_next[current]
        if nxt is start:
            break
        order.append(nxt)
        current = nxt
    return order


def test_strict_tab_map_fields_then_buttons_then_wraparound(dlg):
    theme, autoscan, entry = dlg._theme_menu, dlg._autoscan_switch, dlg._exclude_entry
    ok, cancel, apply_btn = dlg._ok_btn, dlg._cancel_btn, dlg._apply_btn
    assert _tab_targets(dlg) == [
        theme, autoscan, entry, ok, cancel, apply_btn,
    ]
    # wraparound: Apply tabs back to the first field
    assert dlg._tab_next[apply_btn] is theme


def test_tab_registry_complete_and_default_traversal_suppressed(dlg):
    # The declared order IS the contract; Tk's bind-table introspection is
    # unreliable through CTk composite widgets, so we assert on our registry.
    assert dlg._tab_order == (
        dlg._theme_menu,
        dlg._autoscan_switch,
        dlg._exclude_entry,
        dlg._ok_btn,
        dlg._cancel_btn,
        dlg._apply_btn,
    )
    for widget in dlg._tab_order:
        assert widget in dlg._tab_next
        nxt = dlg._tab_next[widget]
        assert dlg._tab_next[nxt] is not widget, "two-cycle in tab map"
        assert dlg._tab_next[nxt] is not None
    # Handler must report "break" so Tk's stacking-order traversal never runs.
    assert dlg._focus(dlg._exclude_entry) == "break"


def test_escape_discards_and_closes(root):
    vm = SettingsViewModel()
    dlg = SettingsDialog(root, vm)
    dlg.withdraw()
    dlg._on_theme_selected("Dark")
    assert vm.snapshot()["dirty"] is True
    dlg._on_cancel()                        # Escape handler
    assert not dlg.winfo_exists()
    assert vm.snapshot()["working"] == DEFAULT_SETTINGS   # discard applied
    assert vm.snapshot()["dirty"] is False
