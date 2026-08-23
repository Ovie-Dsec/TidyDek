"""win32 boundary tests: pointer-width types, SDK constants, live pump thread."""

import sys
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="Windows-only integration"
)

import ctypes

from src.integrations import win32_api as w
from src.integrations.message_window import MessageWindow


# ------------------------------------------------------------- type safety
def test_lparam_lresult_are_pointer_sized_signed():
    assert w.LPARAM is ctypes.c_ssize_t
    assert w.LRESULT is ctypes.c_ssize_t
    assert ctypes.sizeof(w.LPARAM) == ctypes.sizeof(ctypes.c_void_p)


def test_wparam_is_pointer_sized_unsigned():
    assert w.WPARAM is ctypes.c_size_t
    assert ctypes.sizeof(w.WPARAM) == ctypes.sizeof(ctypes.c_void_p)


def test_wndproc_signature_is_pointer_safe():
    proc = w.WNDPROC(lambda hwnd, msg, wp, lp: 0)  # instance exposes materialized types
    assert proc.argtypes == (w.HWND, w.UINT, w.WPARAM, w.LPARAM)
    assert proc.restype is w.LRESULT


def test_defwindowproc_returns_full_width_lresult():
    assert w._DefWindowProcW.restype is w.LRESULT
    assert tuple(w._DefWindowProcW.argtypes) == (w.HWND, w.UINT, w.WPARAM, w.LPARAM)


def test_trackpopupmenuex_and_notifyicon_prototypes_typed():
    assert len(w._TrackPopupMenuEx.argtypes) == 6
    assert w._TrackPopupMenuEx.argtypes[0] is w.HMENU
    assert w._Shell_NotifyIconW.restype is w.BOOL
    import ctypes as ct
    assert w._Shell_NotifyIconW.argtypes[1] == ct.POINTER(w.NOTIFYICONDATAW)


# -------------------------------------------------------------- structures
def test_notifyicondata_layout_matches_sdk_expectations():
    nid = w.NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(nid)
    # Behavioral capacity probes against the fixed SDK buffers.
    nid.szTip = "T" * 100          # fits 128-wchar buffer
    nid.szInfo = "I" * 200         # fits 256-wchar buffer
    nid.szInfoTitle = "t" * 50     # fits 64-wchar buffer
    with pytest.raises(ValueError):
        nid.szTip = "T" * 500      # far beyond any declared capacity
    assert 400 < ctypes.sizeof(nid) < 2048


def test_wndclassex_embeds_wndproc_callback_type():
    field = next(f for f in w.WNDCLASSEXW._fields_ if f[0] == "lpfnWndProc")
    assert field[1] is w.WNDPROC


# -------------------------------------------------------------- constants
@pytest.mark.parametrize(
    "name,expected",
    [
        ("WM_NULL", 0x0000),
        ("WM_CLOSE", 0x0010),
        ("WM_APP", 0x8000),
        ("NIM_ADD", 0x0000),
        ("NIM_MODIFY", 0x0001),
        ("NIM_DELETE", 0x0002),
        ("MF_STRING", 0x0000),
        ("MF_SEPARATOR", 0x0800),
        ("TPM_RIGHTBUTTON", 0x0002),
        ("TPM_BOTTOMALIGN", 0x0020),
        ("TPM_RETURNCMD", 0x0100),
        ("WM_RBUTTONUP", 0x0205),
        ("WM_LBUTTONDBLCLK", 0x0203),
        ("IDI_APPLICATION", 32512),
    ],
)
def test_sdk_constants_match_microsoft_values(name, expected):
    assert getattr(w, name) == expected


# ----------------------------------------------------- live message window
def _wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_message_window_receives_posted_message_with_payload():
    got = []
    seen = threading.Event()
    custom = w.WM_APP + 7

    def handler(message, wp, lp):
        if message == custom:
            got.append((wp, lp))
            seen.set()

    mw = MessageWindow(handler=handler)
    try:
        assert mw.hwnd != 0
        assert mw.post(custom, 11, 22) is True
        assert seen.wait(5), "handler never saw the posted message"
        assert got == [(11, 22)]
    finally:
        mw.close()


def test_invoke_later_executes_on_pump_thread():
    results = []
    mw = MessageWindow()
    try:
        expected_thread = mw.thread_ident
        assert expected_thread != 0
        mw.invoke_later(lambda: results.append(threading.get_ident()))
        assert _wait_until(lambda: bool(results))
        assert results == [expected_thread]
    finally:
        mw.close()


def test_close_is_idempotent_and_joins_pump():
    mw = MessageWindow()
    mw.close()
    mw.close()  # second call must be a safe no-op
    assert mw.wait_closed(2.0) is True


def test_handler_exception_does_not_kill_pump():
    seen_good = threading.Event()
    custom = w.WM_APP + 9

    def bad_then_good(message, wp, lp):
        if message == w.WM_APP + 8:
            raise RuntimeError("boom")
        if message == custom:
            seen_good.set()

    mw = MessageWindow(handler=bad_then_good)
    try:
        mw.post(w.WM_APP + 8)          # will explode inside handler
        mw.post(custom)                # pump must still deliver this
        assert seen_good.wait(5), "pump died after handler exception"
    finally:
        mw.close()
