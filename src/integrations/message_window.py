"""Hidden message-only window with a dedicated pump thread.

Threading contract (critical): a Win32 window belongs to the thread that
created it, and GetMessage on any other thread will never see its messages.
The HWND is therefore created INSIDE the pump thread; __init__ blocks until
creation succeeds (or raises). Shutdown posts WM_CLOSE, whose default
handling destroys the window; our wndproc answers WM_DESTROY with
PostQuitMessage(0) so GetMessage returns 0 and the pump exits cleanly.

Type-safety notes:
- The WNDPROC callable instance is stored as an attribute for the object's
  whole lifetime. If ctypes garbage-collected that callback while Windows
  still held its raw pointer, the process would crash.
- Message parameters flow through win32_api's pointer-width prototypes
  (WPARAM = c_size_t, LPARAM/LRESULT = c_ssize_t), keeping x64 correct.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Callable, Optional

from .win32_api import (
    HWND_MESSAGE,
    MSG,
    WNDCLASSEXW,
    WNDPROC,
    WM_APP,
    WM_CLOSE,
    WM_DESTROY,
    _CreateWindowExW,
    _DefWindowProcW,
    _DispatchMessageW,
    _GetMessageW,
    _GetModuleHandleW,
    _PostMessageW,
    _PostQuitMessage,
    _RegisterClassExW,
    _TranslateMessage,
    byref,
    last_win_error,
    sizeof,
)

MessageHandler = Callable[[int, int, int], None]


class MessageWindow:
    """Invisible top-level window pumping messages on a daemon thread.

    ``handler(message, wparam, lparam)`` runs on the pump thread. Exceptions
    raised inside user callbacks are contained so the pump can never die.
    """

    _WM_INVOKE = WM_APP + 2

    def __init__(self, handler: Optional[MessageHandler] = None) -> None:
        self._handler = handler
        self._lock = threading.Lock()
        self._pending_invocations: dict[int, Callable[[], None]] = {}
        self._invoke_counter = 0
        self._closed = threading.Event()
        self._ready = threading.Event()
        self._init_error: Optional[BaseException] = None

        # GC anchor: Windows keeps a raw pointer to this callable.
        self._wndproc = WNDPROC(self._window_procedure)

        self._hwnd = None
        self.thread_ident = 0
        self._close_started = False
        self._pump_thread = threading.Thread(
            target=self._thread_main, name="TidyDekMsgPump", daemon=True
        )
        self._pump_thread.start()

        if not self._ready.wait(3.0):
            raise RuntimeError("message window initialization timed out")
        if self._init_error is not None:
            raise self._init_error

    # ------------------------------------------------------------------ API
    @property
    def hwnd(self) -> int:
        """Raw HWND as an int (0 when the window is gone)."""
        return int(self._hwnd) if self._hwnd else 0

    def post(self, message: int, wparam: int = 0, lparam: int = 0) -> bool:
        """Queue a message to the window; never blocks."""
        if not self._hwnd:
            return False
        return bool(_PostMessageW(self._hwnd, message, wparam, lparam))

    def invoke_later(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` on the pump thread (FIFO with other posted messages)."""
        with self._lock:
            self._invoke_counter += 1
            key = self._invoke_counter
            self._pending_invocations[key] = fn
        self.post(self._WM_INVOKE, key, 0)

    def wait_closed(self, timeout: float) -> bool:
        return self._closed.wait(timeout)

    def close(self, timeout: float = 3.0) -> None:
        """Idempotent shutdown: WM_CLOSE -> destroy -> WM_DESTROY -> quit."""
        if not self._close_started:
            self._close_started = True
            if self._hwnd:
                _PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        if self._pump_thread is not None:
            self._pump_thread.join(timeout)

    # ------------------------------------------------------------- internals
    def _thread_main(self) -> None:
        self.thread_ident = threading.get_ident()
        try:
            hinstance = _GetModuleHandleW(None)
            class_name = f"TidyDekMsgWindow-{os.getpid()}-{id(self):x}"

            wc = WNDCLASSEXW()
            wc.cbSize = sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinstance
            wc.lpszClassName = class_name
            if not _RegisterClassExW(byref(wc)):
                raise last_win_error()

            hwnd = _CreateWindowExW(
                0,               # dwExStyle
                class_name,      # class
                "",              # window name
                0,               # style
                0, 0, 0, 0,      # x y w h
                HWND_MESSAGE,    # parent -> message-only window
                None,            # menu
                hinstance,
                None,
            )
            if not hwnd:
                raise last_win_error()
            self._hwnd = hwnd
        except Exception as exc:          # surfaced by __init__ via _init_error
            self._init_error = exc
        finally:
            self._ready.set()

        if self._init_error is not None:
            return
        self._pump()

    def _pump(self) -> None:
        msg = MSG()
        while True:
            ret = _GetMessageW(byref(msg), None, 0, 0)
            if ret <= 0:          # 0 = WM_QUIT (posted on WM_DESTROY), -1 error
                break
            _TranslateMessage(byref(msg))
            _DispatchMessageW(byref(msg))
        self._closed.set()

    def _window_procedure(self, hwnd, msg, wparam, lparam):
        try:
            if msg == self._WM_INVOKE:
                key = int(wparam)
                with self._lock:
                    fn = self._pending_invocations.pop(key, None)
                if fn is not None:
                    fn()
                return 0
            if msg == WM_DESTROY:
                # Unblocks GetMessage so close()/join() can complete.
                _PostQuitMessage(0)
            elif self._handler is not None:
                try:
                    self._handler(int(msg), int(wparam), int(lparam))
                except Exception as exc:  # containment: pump must survive
                    sys.stderr.write(f"tray handler error: {exc!r}\n")
            return _DefWindowProcW(hwnd, msg, wparam, lparam)
        except Exception as exc:
            sys.stderr.write(f"wndproc error: {exc!r}\n")
            return 0
