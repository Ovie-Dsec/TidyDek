"""System tray icon built on Shell_NotifyIcon with strict win32 boundaries.

Focus management follows the Microsoft KB135788 contract required for tray
popup menus: SetForegroundWindow MUST run before TrackPopupMenuEx, otherwise
the menu refuses to dismiss when the user clicks elsewhere. Afterwards a
WM_NULL is posted back so the shell regains correct foreground state.

Menu selection uses TPM_RETURNCMD so the chosen command id comes straight
back from TrackPopupMenuEx instead of arriving later via WM_COMMAND.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, Dict, Optional, Sequence, Tuple

from .message_window import MessageWindow
from .win32_api import (
    IDI_APPLICATION,
    MF_SEPARATOR,
    MF_STRING,
    NIF_ICON,
    NIF_MESSAGE,
    NIF_TIP,
    NIM_ADD,
    NIM_DELETE,
    NIM_MODIFY,
    NOTIFYICONDATAW,
    POINT,
    TPM_BOTTOMALIGN,
    TPM_RETURNCMD,
    TPM_RIGHTBUTTON,
    WM_LBUTTONDBLCLK,
    WM_NULL,
    WM_RBUTTONUP,
    _AppendMenuW,
    _CreatePopupMenu,
    _DestroyIcon,
    _DestroyMenu,
    _GetCursorPos,
    _LoadIconW,
    _PostMessageW,
    _SetForegroundWindow,
    _Shell_NotifyIconW,
    _TrackPopupMenuEx,
    byref,
    load_icon_from_file,
    sizeof,
)

MenuItem = Tuple[str, str]          # (label, command_key); empty label = separator
MenuCallback = Callable[[str], None]

_TRAY_CALLBACK_MSG_BASE = 0x8000 + 100   # inside WM_APP range, app-unique


class SystemTrayIcon:
    """Tray icon bound to its own internal :class:`MessageWindow`.

    All callbacks fire on the pump thread; handlers that touch Tk must hop
    threads themselves (e.g. ``window.after(0, ...)``).
    """

    def __init__(
        self,
        *,
        tooltip: str = "TidyDek",
        menu_items: Sequence[MenuItem] = (),
        on_menu: Optional[MenuCallback] = None,
        on_activate: Optional[Callable[[], None]] = None,
        icon_path=None,
    ) -> None:
        self._tooltip = tooltip[:127]
        self._menu_items = tuple(menu_items)
        self._on_menu = on_menu
        self._on_activate = on_activate
        self._callback_msg = _TRAY_CALLBACK_MSG_BASE
        self._id = 1

        self._hicon = None
        if icon_path is not None:
            from pathlib import Path as _Path

            candidate = _Path(icon_path)
            if candidate.is_file():
                self._hicon = load_icon_from_file(str(candidate))
        if not self._hicon:
            self._hicon = _LoadIconW(None, IDI_APPLICATION)
        self._window = MessageWindow(handler=self._handle_message)
        self._added = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ API
    @property
    def window(self) -> MessageWindow:
        return self._window

    def add(self) -> bool:
        with self._lock:
            if self._added or not self._hwnd_valid:
                return False
            nid = self._make_nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)
            ok = bool(_Shell_NotifyIconW(NIM_ADD, byref(nid)))
            self._added = ok
            return ok

    def update_tooltip(self, text: str) -> bool:
        with self._lock:
            if not self._added:
                return False
            nid = self._make_nid(NIF_TIP)
            nid.szTip = text[:127]
            return bool(_Shell_NotifyIconW(NIM_MODIFY, byref(nid)))

    def remove(self) -> None:
        """Idempotent: safe to call multiple times."""
        with self._lock:
            if not self._added:
                return
            nid = NOTIFYICONDATAW()
            nid.cbSize = sizeof(NOTIFYICONDATAW)
            nid.hWnd = self._window.hwnd
            nid.uID = self._id
            _Shell_NotifyIconW(NIM_DELETE, byref(nid))
            self._added = False

    def close(self) -> None:
        self.remove()
        if self._hicon:
            _DestroyIcon(self._hicon)
            self._hicon = None
        self._window.close()

    def __enter__(self) -> "SystemTrayIcon":
        self.add()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ------------------------------------------------------------- internals
    @property
    def _hwnd_valid(self) -> bool:
        return self._window.hwnd != 0

    def _make_nid(self, flags: int) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._window.hwnd
        nid.uID = self._id
        nid.uFlags = flags
        nid.uCallbackMessage = self._callback_msg
        nid.hIcon = self._hicon
        nid.szTip = self._tooltip
        return nid

    def _handle_message(self, message: int, wparam: int, lparam: int) -> None:
        if message != self._callback_msg:
            return
        if lparam == WM_RBUTTONUP:
            self.show_menu()
        elif lparam == WM_LBUTTONDBLCLK and self._on_activate is not None:
            try:
                self._on_activate()
            except Exception as exc:
                sys.stderr.write(f"tray activate error: {exc!r}\n")

    def _populate_menu(self, hmenu: int) -> Dict[int, str]:
        mapping: Dict[int, str] = {}
        cmd_id = 100
        for label, key in self._menu_items:
            if label == "":
                _AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                continue
            if _AppendMenuW(hmenu, MF_STRING, cmd_id, label):
                mapping[cmd_id] = key
                cmd_id += 1
        return mapping

    def show_menu(self) -> None:
        """Focus-safe popup: SetForegroundWindow BEFORE TrackPopupMenuEx."""
        hmenu = _CreatePopupMenu()
        if not hmenu:
            return
        try:
            mapping = self._populate_menu(hmenu)
            # KB135788: without this, the menu will not close on outside click.
            _SetForegroundWindow(self._window.hwnd)
            pt = POINT()
            _GetCursorPos(byref(pt))
            cmd = _TrackPopupMenuEx(
                hmenu,
                TPM_RIGHTBUTTON | TPM_BOTTOMALIGN | TPM_RETURNCMD,
                pt.x,
                pt.y,
                self._window.hwnd,
                None,
            )
        finally:
            _PostMessageW(self._window.hwnd, WM_NULL, 0, 0)
            _DestroyMenu(hmenu)

        key = mapping.get(int(cmd)) if cmd else None
        if key is not None and self._on_menu is not None:
            try:
                self._on_menu(key)
            except Exception as exc:
                sys.stderr.write(f"tray menu error: {exc!r}\n")
