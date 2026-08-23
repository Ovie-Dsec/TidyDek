"""Settings dialog (View layer) bound to SettingsViewModel.

Accessibility contract implemented here and verified by tests:
- Explicit Tab map: theme -> autoscan -> exclude entry -> OK -> Cancel ->
  Apply -> (wraps). Tab/Shift-Tab are rebound on every managed widget, so
  traversal is deterministic regardless of Tk stacking-order quirks.
- Windows HIG button order, left to right: OK, Cancel, Apply.
- Return triggers OK, Escape triggers Cancel; initial focus lands on the
  first field.

The dialog renders ViewModel snapshots only; it holds zero business logic.
"""

from __future__ import annotations

from typing import Mapping, Any

import customtkinter as ctk

from src.viewmodels.settings_viewmodel import SettingsViewModel

THEMES = ("System", "Light", "Dark")


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master, view_model: SettingsViewModel) -> None:
        super().__init__(master)
        self.title("TidyDek Settings")
        self.resizable(False, False)
        self.withdraw()  # build off-screen, reveal when fully laid out

        self._vm = view_model
        self._unsub = view_model.subscribe(self._on_state_changed)
        self._rendering = False

        self.grid_columnconfigure(0, weight=1)

        # ---- field: appearance theme -------------------------------------
        ctk.CTkLabel(self, text="Theme:", anchor="w").grid(
            row=0, column=0, sticky="ew", padx=(16, 16), pady=(16, 4)
        )
        self._theme_menu = ctk.CTkOptionMenu(
            self, values=list(THEMES), command=self._on_theme_selected
        )
        self._theme_menu.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))

        # ---- field: autoscan switch --------------------------------------
        self._autoscan_switch = ctk.CTkSwitch(
            self, text="Scan folder automatically on open",
            command=self._on_autoscan_toggled,
        )
        self._autoscan_switch.grid(
            row=2, column=0, sticky="w", padx=16, pady=(4, 8)
        )

        # ---- field: exclude patterns --------------------------------------
        ctk.CTkLabel(
            self, text="Excluded name patterns (comma separated):", anchor="w"
        ).grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 4))
        self._exclude_entry = ctk.CTkEntry(self)
        self._exclude_entry.bind("<KeyRelease>", self._on_exclude_edited)
        self._exclude_entry.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 12))

        # ---- status line ----------------------------------------------------
        self._status_label = ctk.CTkLabel(self, text="", anchor="w", height=20)
        self._status_label.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 6))

        # ---- Windows HIG button row: OK | Cancel | Apply -------------------
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=6, column=0, sticky="ew", padx=16, pady=(2, 16))
        bar.grid_columnconfigure(0, weight=1)   # spacer pushes trio to the right
        self._ok_btn = ctk.CTkButton(bar, text="OK", width=88,
                                     command=self._on_ok)
        self._ok_btn.grid(row=0, column=1, padx=(0, 6))
        self._cancel_btn = ctk.CTkButton(bar, text="Cancel", width=88,
                                         command=self._on_cancel)
        self._cancel_btn.grid(row=0, column=2, padx=(0, 6))
        self._apply_btn = ctk.CTkButton(bar, text="Apply", width=88,
                                        command=self._on_apply)
        self._apply_btn.grid(row=0, column=3)

        # ---- strict Tab discipline ------------------------------------------
        order = (
            self._theme_menu,
            self._autoscan_switch,
            self._exclude_entry,
            self._ok_btn,
            self._cancel_btn,
            self._apply_btn,
        )
        self._tab_order = order
        self._tab_next: dict[Any, Any] = {}
        for index, widget in enumerate(order):
            nxt = order[(index + 1) % len(order)]
            prv = order[(index - 1) % len(order)]
            self._tab_next[widget] = nxt
            widget.bind("<Tab>", lambda _e, target=nxt: self._focus(target))
            widget.bind("<Shift-Tab>", lambda _e, target=prv: self._focus(target))

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Return>", lambda _e: self._on_ok())
        self.bind("<Escape>", lambda _e: self._on_cancel())

        snap = view_model.snapshot()
        self._paint_widgets(snap["working"])
        self._paint_state(snap)

        # Reveal centered over the parent window.
        self.update_idletasks()
        x = master.winfo_rootx() + max(0, (master.winfo_width() - self.winfo_reqwidth()) // 2)
        y = master.winfo_rooty() + max(0, (master.winfo_height() - self.winfo_reqheight()) // 3)
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self._theme_menu.focus_set()

    # ------------------------------------------------------------- reactions
    @staticmethod
    def _focus(widget) -> str:
        widget.focus_set()
        return "break"          # suppress default traversal

    def _on_state_changed(
        self, snapshot: Mapping[str, Any], changed
    ) -> None:
        working = snapshot.get("working") or {}
        self._paint_widgets(working)
        self._paint_state(snapshot)

    def _paint_widgets(self, working: dict[str, Any]) -> None:
        if self._rendering:
            return
        self._rendering = True
        try:
            general = working.get("general", {})
            scan = working.get("scan", {})
            if self._theme_menu.get() != general.get("theme"):
                self._theme_menu.set(general.get("theme", THEMES[0]))
            wanted_switch = bool(general.get("autoscan_on_open"))
            if bool(self._autoscan_switch.get()) != wanted_switch:
                (self._autoscan_switch.select if wanted_switch
                 else self._autoscan_switch.deselect)()
            patterns = scan.get("exclude_patterns") or []
            text_value = ", ".join(patterns)
            if self._exclude_entry.get() != text_value:
                self._exclude_entry.delete(0, "end")
                self._exclude_entry.insert(0, text_value)
        finally:
            self._rendering = False

    def _paint_state(self, snapshot: Mapping[str, Any]) -> None:
        self._status_label.configure(text=snapshot.get("status", ""))
        self._apply_btn.configure(
            state="normal" if snapshot.get("dirty") else "disabled"
        )

    # --------------------------------------------------------------- intents
    def _on_theme_selected(self, choice: str) -> None:
        self._vm.update_field("general.theme", choice)

    def _on_autoscan_toggled(self) -> None:
        self._vm.update_field(
            "general.autoscan_on_open", bool(int(self._autoscan_switch.get()))
        )

    def _on_exclude_edited(self, _event=None) -> None:
        raw = self._exclude_entry.get()
        patterns = [chunk.strip() for chunk in raw.split(",")]
        self._vm.update_field(
            "scan_rules.exclude_patterns", [p for p in patterns if p]
        )

    def _on_ok(self) -> None:
        if self._vm.apply():
            self.close_dialog()

    def _on_apply(self) -> None:
        self._vm.apply()

    def _on_cancel(self) -> None:
        self._vm.discard()
        self.close_dialog()

    def close_dialog(self) -> None:
        self._unsub()
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
