# Windows-only Wintab (Wacom) minimal wrapper using ctypes
# Focus: expose simple Tablet class to get raw and normalized (x,y,pressure)

from __future__ import annotations

import ctypes
import threading
import time
from typing import Optional, Tuple
from ctypes import wintypes

# ---------- Win32 & helpers ----------
HINSTANCE = wintypes.HMODULE
HICON = wintypes.HANDLE
HCURSOR = wintypes.HANDLE
HBRUSH = wintypes.HANDLE
HMENU = wintypes.HANDLE

class WintabError(RuntimeError):
    pass

# ----- Wintab structs / constants -----
FIX32 = wintypes.LONG  # 16.16 fixed, not converted here

class AXIS(ctypes.Structure):
    _fields_ = [
        ("axMin", wintypes.LONG),
        ("axMax", wintypes.LONG),
        ("axUnits", wintypes.UINT),
        ("axResolution", FIX32),
    ]

class LOGCONTEXTA(ctypes.Structure):
    _fields_ = [
        ("lcName", ctypes.c_char * 40),
        ("lcOptions", wintypes.UINT),
        ("lcStatus", wintypes.UINT),
        ("lcLocks", wintypes.UINT),
        ("lcMsgBase", wintypes.UINT),
        ("lcDevice", wintypes.UINT),
        ("lcPktRate", wintypes.UINT),
        ("lcPktData", wintypes.DWORD),
        ("lcPktMode", wintypes.DWORD),
        ("lcMoveMask", wintypes.DWORD),
        ("lcBtnDnMask", wintypes.DWORD),
        ("lcBtnUpMask", wintypes.DWORD),
        ("lcInOrgX", wintypes.LONG),
        ("lcInOrgY", wintypes.LONG),
        ("lcInOrgZ", wintypes.LONG),
        ("lcInExtX", wintypes.LONG),
        ("lcInExtY", wintypes.LONG),
        ("lcInExtZ", wintypes.LONG),
        ("lcOutOrgX", wintypes.LONG),
        ("lcOutOrgY", wintypes.LONG),
        ("lcOutOrgZ", wintypes.LONG),
        ("lcOutExtX", wintypes.LONG),
        ("lcOutExtY", wintypes.LONG),
        ("lcOutExtZ", wintypes.LONG),
        ("lcSensX", FIX32),
        ("lcSensY", FIX32),
        ("lcSensZ", FIX32),
        ("lcSysMode", wintypes.BOOL),
        ("lcSysOrgX", ctypes.c_int),
        ("lcSysOrgY", ctypes.c_int),
        ("lcSysExtX", ctypes.c_int),
        ("lcSysExtY", ctypes.c_int),
        ("lcSysSensX", ctypes.c_int),
        ("lcSysSensY", ctypes.c_int),
    ]

# Our packet layout must match the requested PK_* order used by pktdef.h.
# For (X, Y, NormalPressure) this ordering is correct on standard Wintab.
class PACKET_XY_PRESS(ctypes.Structure):
    _fields_ = [
        ("pkX", wintypes.LONG),
        ("pkY", wintypes.LONG),
        ("pkNormalPressure", wintypes.UINT),
    ]

# Packet data bits (subset)
PK_X                = 0x0080
PK_Y                = 0x0100
PK_NORMAL_PRESSURE  = 0x0400

# Context options
CXO_SYSTEM   = 0x0001
CXO_PEN      = 0x0002
CXO_MESSAGES = 0x0004

# WTInfo categories and indices (subset)
WTI_DEFCONTEXT = 3
WTI_DEVICES    = 100

# Device axis indices (commonly defined in pktdef.h)
DVC_X           = 0
DVC_Y           = 1
DVC_Z           = 2
DVC_NPRESSURE   = 24   # normal pressure axis
# (Tilt/orientation etc. have other indices; we only use these three.)

# Messages and window flags
WT_DEFBASE  = 0x7FF0
WT_PACKET   = WT_DEFBASE + 0
WM_DESTROY  = 0x0002
WM_CLOSE    = 0x0010
CS_VREDRAW  = 0x0001
CS_HREDRAW  = 0x0002
WS_OVERLAPPED   = 0x00000000
WS_EX_NOACTIVATE= 0x08000000

# ---------- DLLs ----------
_user32   = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

def _load_wintab() -> ctypes.WinDLL:
    try:
        return ctypes.WinDLL("Wintab32.dll")
    except OSError as e:
        raise WintabError(
            "Wintab32.dll not found. Install/enable the Wacom/WinTab driver (or disable Windows Ink for this app)."
        ) from e

# ---------- Win32 window plumbing ----------
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]

class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]

_user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
_user32.RegisterClassW.restype  = wintypes.ATOM
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, HMENU, HINSTANCE, wintypes.LPVOID
]
_user32.CreateWindowExW.restype  = wintypes.HWND
_user32.DefWindowProcW.argtypes  = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype   = ctypes.c_long
_user32.DestroyWindow.argtypes   = [wintypes.HWND]
_user32.DestroyWindow.restype    = wintypes.BOOL
_user32.GetMessageW.argtypes     = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.GetMessageW.restype      = wintypes.BOOL
_user32.TranslateMessage.argtypes= [ctypes.POINTER(MSG)]
_user32.DispatchMessageW.argtypes= [ctypes.POINTER(MSG)]
_user32.PostQuitMessage.argtypes = [ctypes.c_int]
_user32.PostMessageW.argtypes    = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype  = wintypes.HMODULE

_instances = {}           # hwnd -> Tablet
_global_wndproc_ref = None

# ---------- Tablet wrapper ----------
class Tablet:
    """
    Headless WinTab reader.
    Methods:
      - start()/stop()
      - read() -> raw ints (x, y, p)
      - read_normalized() -> floats in [0,1]
    """
    def __init__(self, smooth_alpha: Optional[float] = 0.12):
        self._wt: Optional[ctypes.WinDLL] = None
        self._hctx = None
        self._hwnd = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._latest_lock = threading.Lock()
        self._latest_raw: Optional[Tuple[int, int, int]] = None
        self._x_axis = AXIS()
        self._y_axis = AXIS()
        self._p_axis = AXIS()
        self._smooth_alpha = smooth_alpha
        self._nx = self._ny = self._np = None  # smoothed normalized

    # --- public API ---
    def start(self, wait_ready: bool = True, timeout: float = 3.0):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, name="WintabThread", daemon=True)
        self._thread.start()
        if wait_ready and not self._ready.wait(timeout):
            raise WintabError("Timed out starting Wintab thread")

    def stop(self):
        self._stop.set()
        if self._hwnd:
            _user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._wt = None
        self._hwnd = None
        self._hctx = None

    def __enter__(self): self.start(); return self
    def __exit__(self, *_): self.stop()

    def read(self, timeout: Optional[float] = None) -> Tuple[int, int, int]:
        """Raw integers from the device coordinate space."""
        if self._hctx is None:
            raise WintabError("Tablet context not available")
        if timeout:
            deadline = time.time() + timeout
            while time.time() < deadline:
                with self._latest_lock:
                    if self._latest_raw is not None:
                        return self._latest_raw
                time.sleep(0.01)
        with self._latest_lock:
            if self._latest_raw is None:
                raise WintabError("No tablet data yet")
            return self._latest_raw

    def read_normalized(self, timeout: Optional[float] = None) -> Tuple[float, float, float]:
        """(x,y,p) normalized to [0,1] with optional EMA smoothing."""
        rx, ry, rp = self.read(timeout)
        x = self._norm(self._x_axis, rx)
        y = self._norm(self._y_axis, ry)
        p = self._norm(self._p_axis, rp)
        if self._smooth_alpha is None:
            return x, y, p
        self._nx = self._ema(self._nx, x)
        self._ny = self._ema(self._ny, y)
        self._np = self._ema(self._np, p)
        return self._nx, self._ny, self._np

    # --- internals ---
    def _thread_main(self):
        try:
            self._wt = _load_wintab()
            self._bind()
            self._register_wc()
            self._create_hwnd()
            ok_ctx = self._open_ctx()
            if ok_ctx:
                self._query_axes()  # <-- ranges for normalization
            self._ready.set()
            if ok_ctx:
                self._msg_loop()
        finally:
            self._close_ctx()
            self._destroy_hwnd()

    def _bind(self):
        wt = self._wt
        wt.WTInfoA.argtypes  = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
        wt.WTInfoA.restype   = wintypes.UINT
        wt.WTOpenA.argtypes  = [wintypes.HWND, ctypes.POINTER(LOGCONTEXTA), wintypes.BOOL]
        wt.WTOpenA.restype   = ctypes.c_void_p  # HCTX
        wt.WTClose.argtypes  = [ctypes.c_void_p]
        wt.WTClose.restype   = wintypes.BOOL
        wt.WTPacket.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p]
        wt.WTPacket.restype  = wintypes.BOOL

    def _register_wc(self):
        global _global_wndproc_ref
        if _global_wndproc_ref is None:
            _global_wndproc_ref = WNDPROC(_global_wndproc)
        wc = WNDCLASSW()
        wc.style = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = _global_wndproc_ref
        wc.hInstance = _kernel32.GetModuleHandleW(None)
        wc.lpszClassName = "WintabHiddenWindow"
        _user32.RegisterClassW(ctypes.byref(wc))

    def _create_hwnd(self):
        hInstance = _kernel32.GetModuleHandleW(None)
        hwnd = _user32.CreateWindowExW(
            WS_EX_NOACTIVATE, "WintabHiddenWindow", "Wintab Hidden Window",
            WS_OVERLAPPED, 0, 0, 0, 0, None, None, hInstance, None
        )
        if not hwnd:
            raise WintabError("Failed to create hidden window")
        self._hwnd = hwnd
        _instances[hwnd] = self

    def _destroy_hwnd(self):
        hwnd = self._hwnd
        if hwnd:
            _instances.pop(hwnd, None)
            _user32.DestroyWindow(hwnd)
            self._hwnd = None

    def _open_ctx(self) -> bool:
        wt = self._wt
        lc = LOGCONTEXTA()
        if wt.WTInfoA(WTI_DEFCONTEXT, 0, ctypes.byref(lc)) == 0:
            return False  # no tablet/driver
        lc.lcPktData = PK_X | PK_Y | PK_NORMAL_PRESSURE
        lc.lcMoveMask = lc.lcPktData
        lc.lcPktMode = 0
        lc.lcOptions |= CXO_MESSAGES  # receive WT_PACKET messages
        lc.lcMsgBase = WT_DEFBASE
        hctx = wt.WTOpenA(self._hwnd, ctypes.byref(lc), True)
        if not hctx:
            return False
        self._hctx = hctx
        return True

    def _close_ctx(self):
        if self._wt and self._hctx:
            self._wt.WTClose(self._hctx)
            self._hctx = None

    def _query_axes(self):
        # Fill axis ranges for normalization
        self._wt.WTInfoA(WTI_DEVICES, DVC_X, ctypes.byref(self._x_axis))
        self._wt.WTInfoA(WTI_DEVICES, DVC_Y, ctypes.byref(self._y_axis))
        self._wt.WTInfoA(WTI_DEVICES, DVC_NPRESSURE, ctypes.byref(self._p_axis))

    def _msg_loop(self):
        msg = MSG()
        while not self._stop.is_set():
            res = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if res == 0:   # WM_QUIT
                break
            if res == -1:  # error
                break
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def _handle_msg(self, hwnd, msg, wParam, lParam):
        if msg == WT_PACKET and self._wt and self._hctx:
            pkt = PACKET_XY_PRESS()
            # WT_PACKET: wParam=pkt serial, lParam=HCTX
            ok = self._wt.WTPacket(ctypes.c_void_p(lParam), wParam, ctypes.byref(pkt))
            if ok:
                with self._latest_lock:
                    self._latest_raw = (int(pkt.pkX), int(pkt.pkY), int(pkt.pkNormalPressure))
                return 0
        elif msg == WM_CLOSE:
            _user32.DestroyWindow(hwnd); return 0
        elif msg == WM_DESTROY:
            _user32.PostQuitMessage(0); return 0
        return _user32.DefWindowProcW(hwnd, msg, wParam, lParam)

    # --- math helpers ---
    @staticmethod
    def _norm(axis: AXIS, v: int) -> float:
        lo, hi = int(axis.axMin), int(axis.axMax)
        if hi == lo:
            return 0.0
        f = (v - lo) / float(hi - lo)
        return 0.0 if f < 0 else 1.0 if f > 1 else f

    def _ema(self, prev, new):
        if new is None: return prev
        if prev is None: return new
        a = float(self._smooth_alpha)
        return (1 - a) * prev + a * new


# Global wndproc: dispatch to instance
@WNDPROC
def _global_wndproc(hwnd, msg, wParam, lParam):
    inst = _instances.get(hwnd)
    if inst is not None:
        return inst._handle_msg(hwnd, msg, wParam, lParam)
    return _user32.DefWindowProcW(hwnd, msg, wParam, lParam)


# --------- Example ----------
if __name__ == "__main__":
    with Tablet(smooth_alpha=0.12) as t:
        while True:
            try:
                x, y, p = t.read_normalized(timeout=2.0)
                print(f"x={x:.3f}  y={y:.3f}  p={p:.3f}")
                time.sleep(0.01)
            except KeyboardInterrupt:
                break
