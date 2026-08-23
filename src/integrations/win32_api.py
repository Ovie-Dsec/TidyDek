"""Raw win32 declarations: the SINGLE module in TidyDek allowed to touch ctypes.

Boundary discipline (enforced by tests/test_architecture.py):
- Every imported function declares explicit ``argtypes`` and ``restype``.
- Pointer-width types follow the Microsoft SDK exactly:
  LRESULT / LPARAM / LONG_PTR  ->  c_ssize_t   (signed, 8 bytes on x64)
  WPARAM   / UINT_PTR / SIZE_PTR ->  c_size_t   (unsigned, 8 bytes on x64)
  Handles (HWND, HMENU, HICON, ...) -> c_void_p
- Using c_int/c_uint for these truncates 64-bit handles and corrupts the
  stack on x64; that failure mode is pinned by unit tests.
"""

from __future__ import annotations

import sys

if not sys.platform.startswith("win"):
    raise OSError("win32_api is only importable on Windows")

import ctypes
from ctypes import (
    WINFUNCTYPE,
    POINTER,
    Structure,
    Union,
    byref,
    cast,
    sizeof,
    c_ssize_t,
    c_size_t,
)
from ctypes import c_char, c_int, c_ubyte, c_uint, c_void_p, c_wchar
from ctypes import wintypes
from typing import Optional

# ------------------------------------------------------------------ aliases
UINT = c_uint                       # wintypes.UINT
DWORD = wintypes.DWORD              # unsigned long, 4 bytes
BOOL = wintypes.BOOL                # c_long
WORD = wintypes.WORD
ATOM = WORD
LPCWSTR = wintypes.LPCWSTR
LPVOID = c_void_p

HWND = c_void_p
HMENU = c_void_p
HICON = c_void_p
HCURSOR = c_void_p
HBRUSH = c_void_p
HINSTANCE = c_void_p
HMODULE = c_void_p

LONG_PTR = c_ssize_t
LRESULT = c_ssize_t                 # signed pointer-sized  (SDK: LONG_PTR)
LPARAM = c_ssize_t                  # signed pointer-sized
WPARAM = c_size_t                   # unsigned pointer-sized (SDK: UINT_PTR)
UINT_PTR = c_size_t

WNDPROC = WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

# ------------------------------------------------------------- structures
class POINT(Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(Structure):
    _fields_ = [
        ("hwnd", HWND),
        ("message", UINT),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", DWORD),
        ("pt", POINT),
    ]


class _NotifyVersionUnion(Union):
    _fields_ = [("uTimeout", UINT), ("uVersion", UINT)]


class NOTIFYICONDATAW(Structure):
    _anonymous_ = ("version_union",)
    _fields_ = [
        ("cbSize", DWORD),
        ("hWnd", HWND),
        ("uID", UINT),
        ("uFlags", UINT),
        ("uCallbackMessage", UINT),
        ("hIcon", HICON),
        ("szTip", c_wchar * 128),
        ("dwState", DWORD),
        ("dwStateMask", DWORD),
        ("szInfo", c_wchar * 256),
        ("version_union", _NotifyVersionUnion),
        ("szInfoTitle", c_wchar * 64),
        ("dwInfoFlags", DWORD),
        ("guidItem", c_ubyte * 16),   # GUID kept as raw bytes
        ("hBalloonIcon", HICON),
    ]


class WNDCLASSEXW(Structure):
    _fields_ = [
        ("cbSize", UINT),
        ("style", UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", c_int),
        ("cbWndExtra", c_int),
        ("hInstance", HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", LPCWSTR),
        ("lpszClassName", LPCWSTR),
        ("hIconSm", HICON),
    ]


# -------------------------------------------------------------- constants
WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_APP = 0x8000

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B

NIM_ADD = 0x0000
NIM_MODIFY = 0x0001
NIM_DELETE = 0x0002
NIM_SETFOCUS = 0x0003
NIM_SETVERSION = 0x0004

NIF_MESSAGE = 0x0001
NIF_ICON = 0x0002
NIF_TIP = 0x0004
NIF_STATE = 0x0008
NIF_INFO = 0x0010
NIF_REALTIME = 0x0040
NIF_SHOWTIP = 0x0080

MF_STRING = 0x0000
MF_SEPARATOR = 0x0800

TPM_LEFTBUTTON = 0x0000
TPM_RIGHTBUTTON = 0x0002
TPM_BOTTOMALIGN = 0x0020
TPM_NONOTIFY = 0x0080
TPM_RETURNCMD = 0x0100

GWLP_WNDPROC = -4                   # index, sign-extended by caller
HWND_MESSAGE = HWND(-3)             # special message-only parent

IDI_APPLICATION = 32512             # MAKEINTRESOURCE id
IMAGE_ICON = 1
LR_DEFAULTSIZE = 0x0040
LR_LOADFROMFILE = 0x0010

MB_OK = 0x00000000
MB_ICONERROR = 0x00000010
MB_ICONINFORMATION = 0x00000040
MB_SETFOREGROUND = 0x00010000
MB_TOPMOST = 0x00040000
MB_YESNO = 0x00000004
IDYES = 6

# ---------------------------------------------------------- COM / taskbar
HRESULT = ctypes.HRESULT
ULONGLONG = ctypes.c_uint64
GUID = ctypes.c_ubyte * 16


def guid_from(text: str) -> ctypes.Array:
    """'{XXXXXXXX-...}' -> little-endian GUID bytes for COM calls."""
    import uuid

    return GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


CLSCTX_INPROC_SERVER = 0x00000001
COINIT_APARTMENTTHREADED = 0x2
RPC_E_CHANGED_MODE = 0x80010106

# Taskbar button progress states (ITaskbarList3::SetProgressState)
TBPF_NOPROGRESS = 0x0
TBPF_INDETERMINATE = 0x1
TBPF_NORMAL = 0x2
TBPF_ERROR = 0x4
TBPF_PAUSED = 0x8

_CLSID_TaskbarList = guid_from("{56FDF344-FD6D-11d0-958A-006097C9A090}")
_IID_ITaskbarList3 = guid_from("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}")

# ------------------------------------------------------------- prototypes
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_ole32 = ctypes.WinDLL("ole32", use_last_error=True)

_GetModuleHandleW = _kernel32.GetModuleHandleW
_GetModuleHandleW.argtypes = [LPCWSTR]
_GetModuleHandleW.restype = HMODULE

_RegisterClassExW = _user32.RegisterClassExW
_RegisterClassExW.argtypes = [POINTER(WNDCLASSEXW)]
_RegisterClassExW.restype = ATOM

_CreateWindowExW = _user32.CreateWindowExW
_CreateWindowExW.argtypes = [
    DWORD, LPCWSTR, LPCWSTR, DWORD,
    c_int, c_int, c_int, c_int,
    HWND, HMENU, HINSTANCE, LPVOID,
]
_CreateWindowExW.restype = HWND

_DefWindowProcW = _user32.DefWindowProcW
_DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]
_DefWindowProcW.restype = LRESULT               # pointer-wide on purpose

_DestroyWindow = _user32.DestroyWindow
_DestroyWindow.argtypes = [HWND]
_DestroyWindow.restype = BOOL

_PostMessageW = _user32.PostMessageW
_PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
_PostMessageW.restype = BOOL

_PostQuitMessage = _user32.PostQuitMessage
_PostQuitMessage.argtypes = [c_int]
_PostQuitMessage.restype = None

_GetMessageW = _user32.GetMessageW
_GetMessageW.argtypes = [POINTER(MSG), HWND, UINT, UINT]
_GetMessageW.restype = BOOL                     # may return -1 (error)

_TranslateMessage = _user32.TranslateMessage
_TranslateMessage.argtypes = [POINTER(MSG)]
_TranslateMessage.restype = BOOL

_DispatchMessageW = _user32.DispatchMessageW
_DispatchMessageW.argtypes = [POINTER(MSG)]
_DispatchMessageW.restype = LRESULT

_SetForegroundWindow = _user32.SetForegroundWindow
_SetForegroundWindow.argtypes = [HWND]
_SetForegroundWindow.restype = BOOL

_GetCursorPos = _user32.GetCursorPos
_GetCursorPos.argtypes = [POINTER(POINT)]
_GetCursorPos.restype = BOOL

_CreatePopupMenu = _user32.CreatePopupMenu
_CreatePopupMenu.argtypes = []
_CreatePopupMenu.restype = HMENU

_AppendMenuW = _user32.AppendMenuW
_AppendMenuW.argtypes = [HMENU, UINT, UINT_PTR, LPCWSTR]
_AppendMenuW.restype = BOOL

_TrackPopupMenuEx = _user32.TrackPopupMenuEx
_TrackPopupMenuEx.argtypes = [HMENU, UINT, c_int, c_int, HWND, LPVOID]
_TrackPopupMenuEx.restype = BOOL                # carries TPM_RETURNCMD id

_DestroyMenu = _user32.DestroyMenu
_DestroyMenu.argtypes = [HMENU]
_DestroyMenu.restype = BOOL

_LoadIconW = _user32.LoadIconW
_LoadIconW.argtypes = [HINSTANCE, LONG_PTR]     # 2nd arg is MAKEINTRESOURCE id
_LoadIconW.restype = HICON

_LoadImageW = _user32.LoadImageW
_LoadImageW.argtypes = [HINSTANCE, LPCWSTR, UINT, c_int, c_int, UINT]
_LoadImageW.restype = HICON

_MessageBoxW = _user32.MessageBoxW
_MessageBoxW.argtypes = [HWND, LPCWSTR, LPCWSTR, UINT]
_MessageBoxW.restype = c_int

_DestroyIcon = _user32.DestroyIcon
_DestroyIcon.argtypes = [HICON]
_DestroyIcon.restype = BOOL

_Shell_NotifyIconW = _shell32.Shell_NotifyIconW
_Shell_NotifyIconW.argtypes = [DWORD, POINTER(NOTIFYICONDATAW)]
_Shell_NotifyIconW.restype = BOOL

# ---- COM activation for the taskbar progress bridge -----------------------
_CoInitializeEx = _ole32.CoInitializeEx
_CoInitializeEx.argtypes = [LPVOID, DWORD]
_CoInitializeEx.restype = HRESULT

_CoCreateInstance = _ole32.CoCreateInstance
_CoCreateInstance.argtypes = [
    POINTER(GUID), LPVOID, DWORD, POINTER(GUID), POINTER(LPVOID),
]
_CoCreateInstance.restype = HRESULT


def last_win_error() -> OSError:
    """Build an OSError from the captured last-error of the DLL calls above."""
    return ctypes.WinError(ctypes.get_last_error())


def load_icon_from_file(path: str) -> Optional[HICON]:
    """Load an .ico from disk (None on failure; caller falls back)."""
    handle = _LoadImageW(None, path, IMAGE_ICON, 0, 0,
                         LR_DEFAULTSIZE | LR_LOADFROMFILE)
    return handle or None


def show_message_box(title: str, text: str, *, icon: int = MB_ICONERROR,
                     buttons: int = MB_OK) -> int:
    """Native message box; returns the pressed button id (e.g. IDYES)."""
    flags = icon | buttons | MB_SETFOREGROUND | MB_TOPMOST
    return int(_MessageBoxW(None, text, title, flags))
