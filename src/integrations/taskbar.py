"""Windows taskbar progress bridge over ITaskbarList3.

COM notes:
- The interface pointer is obtained once per bridge via CoCreateInstance on
  the calling thread; the View constructs this ON THE UI THREAD and only
  calls it from the UI thread (the HWND's owner thread).
- Method dispatch goes through the raw vtable: index 3 = HrInit,
  9 = SetProgressValue(hwnd, completed, total), 10 = SetProgressState(hwnd,
  flags). All signatures use win32_api's pointer-width/handle types.
- Every public call is failure-silent by design: taskbar feedback is purely
  cosmetic and must never take the application down.
"""

from __future__ import annotations

import logging
from typing import Callable

from .win32_api import (
    CLSCTX_INPROC_SERVER,
    COINIT_APARTMENTTHREADED,
    HRESULT,
    HWND,
    LPVOID,
    POINTER,
    RPC_E_CHANGED_MODE,
    TBPF_INDETERMINATE,
    TBPF_NOPROGRESS,
    ULONGLONG,
    UINT,
    WINFUNCTYPE,
    _CLSID_TaskbarList,
    _CoCreateInstance,
    _CoInitializeEx,
    _IID_ITaskbarList3,
    byref,
    c_void_p,
    cast,
)

logger = logging.getLogger("tidydek.taskbar")

_HRESULT_METHOD = WINFUNCTYPE(HRESULT, c_void_p)
_PROGRESS_VALUE = WINFUNCTYPE(HRESULT, c_void_p, HWND, ULONGLONG, ULONGLONG)
_PROGRESS_STATE = WINFUNCTYPE(HRESULT, c_void_p, HWND, UINT)

_VTBL_HR_INIT = 3
_VTBL_SET_PROGRESS_VALUE = 9
_VTBL_SET_PROGRESS_STATE = 10


class TaskbarProgress:
    """Determinate/indeterminate progress on the taskbar button of one HWND."""

    def __init__(self, hwnd_provider: Callable[[], int]) -> None:
        self._hwnd_provider = hwnd_provider
        self._iface_addr: int | None = None
        self._initialized = False

    # ------------------------------------------------------------ internals
    @staticmethod
    def _vtbl_entry(iface_addr: int, index: int) -> int:
        """Resolve one vtable slot of a COM interface to a callable address."""
        table = cast(iface_addr, POINTER(c_void_p))
        return table[index].value or 0

    def _ensure_initialized(self) -> bool:
        if self._initialized:
            return True
        hwnd = self._hwnd_provider()
        if not hwnd:
            return False
        try:
            hr = _CoInitializeEx(None, COINIT_APARTMENTTHREADED)
            if hr not in (0, RPC_E_CHANGED_MODE):  # S_OK / S_FALSE / changed
                logger.debug("CoInitializeEx failed: 0x%08X", hr & 0xFFFFFFFF)
                return False

            iface_ptr = LPVOID()
            hr = _CoCreateInstance(
                byref(_CLSID_TaskbarList),
                None,
                CLSCTX_INPROC_SERVER,
                byref(_IID_ITaskbarList3),
                byref(iface_ptr),
            )
            if hr != 0 or not iface_ptr.value:
                logger.debug("CoCreateInstance(TaskbarList) failed: 0x%08X",
                             hr & 0xFFFFFFFF)
                return False

            iface_addr = iface_ptr.value
            hr_init = _HRESULT_METHOD(
                self._vtbl_entry(iface_addr, _VTBL_HR_INIT)
            )
            if hr_init(iface_addr) != 0:
                logger.debug("ITaskbarList3::HrInit failed")
                return False

            self._iface_addr = iface_addr
            self._initialized = True
            return True
        except Exception as exc:  # cosmetic feature: never fatal
            logger.debug("taskbar init error: %r", exc)
            return False

    def _set_state(self, flags: int) -> None:
        if not self._ensure_initialized() or self._iface_addr is None:
            return
        try:
            method = _PROGRESS_STATE(
                self._vtbl_entry(self._iface_addr, _VTBL_SET_PROGRESS_STATE)
            )
            method(self._iface_addr, HWND(self._hwnd_provider()), flags)
        except Exception as exc:
            logger.debug("SetProgressState error: %r", exc)

    def _set_value(self, completed: int, total: int) -> None:
        if not self._ensure_initialized() or self._iface_addr is None:
            return
        try:
            method = _PROGRESS_VALUE(
                self._vtbl_entry(self._iface_addr, _VTBL_SET_PROGRESS_VALUE)
            )
            method(self._iface_addr, HWND(self._hwnd_provider()),
                   ULONGLONG(completed), ULONGLONG(total))
        except Exception as exc:
            logger.debug("SetProgressValue error: %r", exc)

    # ------------------------------------------------------------- public
    def start_indeterminate(self) -> None:
        self._set_value(0, 0)
        self._set_state(TBPF_INDETERMINATE)

    def clear(self) -> None:
        self._set_state(TBPF_NOPROGRESS)
