# wintab_wrapper.py
# Windows-only Wintab (Wacom) wrapper using ctypes and Queues

from __future__ import annotations

import ctypes
import threading
import queue
import traceback
import sys
from typing import Optional, Tuple
from ctypes import wintypes

# --- DEBUG CONFIG ---
DEBUG = False


def log(msg):
    if DEBUG:
        print(f"[Wintab] {msg}")
        sys.stdout.flush()


# ---------- Win32 Types & Helpers ----------
if ctypes.sizeof(ctypes.c_void_p) == 8:
    LPARAM = ctypes.c_int64
    WPARAM = ctypes.c_uint64
else:
    LPARAM = ctypes.c_long
    WPARAM = ctypes.c_uint

HANDLE = ctypes.c_void_p
HWND = HANDLE
HINSTANCE = HANDLE
HICON = HANDLE
HCURSOR = HANDLE
HBRUSH = HANDLE
HMENU = HANDLE


class WintabError(RuntimeError):
    pass


# ----- Wintab structs / constants -----
FIX32 = wintypes.LONG


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


# Packet data bits
PK_CONTEXT = 0x0001
PK_STATUS = 0x0002
PK_TIME = 0x0004
PK_CHANGED = 0x0008
PK_SERIAL = 0x0010
PK_CURSOR = 0x0020
PK_BUTTONS = 0x0040
PK_X = 0x0080
PK_Y = 0x0100
PK_Z = 0x0200
PK_NORMAL_PRESSURE = 0x0400
PK_TANGENT_PRESSURE = 0x0800
PK_ORIENTATION = 0x1000
PK_ROTATION = 0x2000

# Context options
CXO_SYSTEM = 0x0001
CXO_PEN = 0x0002
CXO_MESSAGES = 0x0004
CXO_MARGIN = 0x8000

WTI_DEFCONTEXT = 3
WTI_DEVICES = 100
DVC_X = 12
DVC_Y = 13
DVC_NPRESSURE = 15

WT_DEFBASE = 0x7FF0
WT_PACKET = WT_DEFBASE + 0
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_NULL = 0x0000

CS_VREDRAW = 0x0001
CS_HREDRAW = 0x0002
WS_OVERLAPPED = 0x00000000
WS_EX_NOACTIVATE = 0x08000000

# ---------- DLLs ----------
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _load_wintab() -> ctypes.WinDLL:
    log("Loading Wintab32.dll...")
    try:
        dll = ctypes.WinDLL("Wintab32.dll")
        log(f"Wintab32.dll loaded at {dll}")
        return dll
    except OSError as e:
        log("FAILED to load Wintab32.dll")
        raise WintabError("Wintab32.dll not found. Is the tablet driver installed?") from e


# ---------- Win32 window plumbing ----------
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_int64, HWND, wintypes.UINT, WPARAM, LPARAM)


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
        ("hwnd", HWND),
        ("message", wintypes.UINT),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


_user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
_user32.RegisterClassW.restype = wintypes.ATOM
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    HWND, HMENU, HINSTANCE, ctypes.c_void_p
]
_user32.CreateWindowExW.restype = HWND
_user32.PostMessageW.argtypes = [HWND, wintypes.UINT, WPARAM, LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.DefWindowProcW.argtypes = [HWND, wintypes.UINT, WPARAM, LPARAM]
_user32.DefWindowProcW.restype = ctypes.c_int64

_instances = {}
_global_wndproc_ref = None


# ---------- Tablet wrapper ----------
class Tablet:
    def __init__(self, smooth_alpha: Optional[float] = 0.12):
        self._wt: Optional[ctypes.WinDLL] = None
        self._hctx = None
        self._hwnd = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._queue = queue.Queue(maxsize=50)

        self._x_axis = AXIS()
        self._y_axis = AXIS()
        self._p_axis = AXIS()
        self._smooth_alpha = smooth_alpha
        self._nx = self._ny = self._np = None

        self._off_x = -1
        self._off_y = -1
        self._off_p = -1

    def start(self, wait_ready: bool = True, timeout: float = 3.0):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, name="WintabThread", daemon=True)
        self._thread.start()
        if wait_ready:
            if not self._ready.wait(timeout):
                raise WintabError("Timed out starting Wintab thread")
            if self._hctx is None:
                raise WintabError("Failed to open Wintab context.")

    def stop(self):
        self._stop.set()
        if self._hwnd:
            _user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._wt = None
        self._hwnd = None
        self._hctx = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    def read(self, timeout: Optional[float] = None) -> Tuple[int, int, int]:
        if self._hctx is None:
            raise WintabError("Tablet context not available")
        return self._queue.get(block=True, timeout=timeout)

    def read_normalized(self, timeout: Optional[float] = None) -> Tuple[float, float, float]:
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

            # 1. Query device axes FIRST to get max coords
            self._query_axes()
            log(f"Tablet Ranges - X: 0-{self._x_axis.axMax}, Y: 0-{self._y_axis.axMax}, Press: 0-{self._p_axis.axMax}")

            # 2. Open context with those coords
            ok_ctx = self._open_ctx()
            if ok_ctx:
                self._validate_context()
                log("Context validated.")

            self._ready.set()

            if ok_ctx:
                self._msg_loop()
        except Exception as e:
            print(f"Internal Wintab Error: {e}")
            traceback.print_exc()
        finally:
            self._close_ctx()
            self._destroy_hwnd()

    def _bind(self):
        wt = self._wt
        wt.WTInfoA.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
        wt.WTInfoA.restype = wintypes.UINT
        wt.WTOpenA.argtypes = [HWND, ctypes.POINTER(LOGCONTEXTA), wintypes.BOOL]
        wt.WTOpenA.restype = ctypes.c_void_p
        wt.WTClose.argtypes = [ctypes.c_void_p]
        wt.WTPacket.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
        wt.WTPacket.restype = wintypes.BOOL
        try:
            wt.WTGetA.argtypes = [ctypes.c_void_p, ctypes.POINTER(LOGCONTEXTA)]
            wt.WTGetA.restype = wintypes.BOOL
        except AttributeError:
            log("Warning: WTGetA not found in DLL.")

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
            raise WintabError(f"CreateWindow failed: {ctypes.WinError()}")
        self._hwnd = hwnd
        _instances[hwnd] = self

    def _destroy_hwnd(self):
        if self._hwnd:
            _instances.pop(self._hwnd, None)
            _user32.DestroyWindow(self._hwnd)
            self._hwnd = None

    def _open_ctx(self) -> bool:
        wt = self._wt
        lc = LOGCONTEXTA()

        # Get defaults
        if wt.WTInfoA(WTI_DEFCONTEXT, 0, ctypes.byref(lc)) == 0:
            return False

        if self._x_axis.axMax > 0:
            lc.lcInOrgX = 0
            lc.lcInExtX = self._x_axis.axMax
            lc.lcOutOrgX = 0
            lc.lcOutExtX = self._x_axis.axMax  # 1:1 mapping

        if self._y_axis.axMax > 0:
            lc.lcInOrgY = 0
            lc.lcInExtY = self._y_axis.axMax
            lc.lcOutOrgY = 0
            lc.lcOutExtY = self._y_axis.axMax  # 1:1 mapping

        if self._p_axis.axMax > 0:
            lc.lcOutExtZ = self._p_axis.axMax  # Using Z slot for pressure scaling often helps

        lc.lcPktData = PK_X | PK_Y | PK_NORMAL_PRESSURE
        lc.lcMoveMask = PK_X | PK_Y | PK_NORMAL_PRESSURE
        lc.lcPktMode = 0  # Absolute mode

        # Ensure we catch messages
        lc.lcOptions |= CXO_MESSAGES
        lc.lcOptions |= CXO_MARGIN

        # We strip CXO_SYSTEM to ensure we are getting raw digitizer data,
        # not system cursor coordinates which might be clipped.
        lc.lcOptions &= ~CXO_SYSTEM

        hctx = wt.WTOpenA(self._hwnd, ctypes.byref(lc), True)
        if not hctx:
            return False

        self._hctx = hctx
        return True

    def _validate_context(self):
        lc = LOGCONTEXTA()
        if hasattr(self._wt, 'WTGetA'):
            self._wt.WTGetA(self._hctx, ctypes.byref(lc))
            pkt_mask = lc.lcPktData
            log(f"Active Context PktData: {hex(pkt_mask)}")
        else:
            pkt_mask = PK_X | PK_Y | PK_NORMAL_PRESSURE

        current_offset = 0

        def check_field(mask, flag, size=4):
            nonlocal current_offset
            offset = -1
            if mask & flag:
                offset = current_offset
                current_offset += size
            return offset

        check_field(pkt_mask, PK_CONTEXT)
        check_field(pkt_mask, PK_STATUS)
        check_field(pkt_mask, PK_TIME)
        check_field(pkt_mask, PK_CHANGED)
        check_field(pkt_mask, PK_SERIAL)
        check_field(pkt_mask, PK_CURSOR)
        check_field(pkt_mask, PK_BUTTONS)

        self._off_x = check_field(pkt_mask, PK_X)
        self._off_y = check_field(pkt_mask, PK_Y)
        self._off_z = check_field(pkt_mask, PK_Z)
        self._off_p = check_field(pkt_mask, PK_NORMAL_PRESSURE)

        log(f"Offsets: X={self._off_x}, Y={self._off_y}, P={self._off_p}. Total packet size ~{current_offset}")

    def _close_ctx(self):
        if self._wt and self._hctx:
            self._wt.WTClose(self._hctx)
            self._hctx = None

    def _query_axes(self):
        # Queries the dimensions of the tablet hardware (Max X, Max Y, Max Pressure)
        self._wt.WTInfoA(WTI_DEVICES, DVC_X, ctypes.byref(self._x_axis))
        self._wt.WTInfoA(WTI_DEVICES, DVC_Y, ctypes.byref(self._y_axis))
        self._wt.WTInfoA(WTI_DEVICES, DVC_NPRESSURE, ctypes.byref(self._p_axis))

    def _handle_msg(self, hwnd, msg, wParam, lParam):
        if self._stop.is_set():
            return _user32.DefWindowProcW(hwnd, msg, wParam, lParam)

        if msg == WT_PACKET and self._wt and self._hctx:
            serial = int(wParam)
            hctx_arg = ctypes.c_void_p(lParam)

            buf = (ctypes.c_byte * 128)()

            if self._wt.WTPacket(hctx_arg, serial, ctypes.byref(buf)):
                x, y, p = 0, 0, 0

                def read_long(offset):
                    return int.from_bytes(buf[offset:offset + 4], byteorder='little', signed=True)

                def read_uint(offset):
                    return int.from_bytes(buf[offset:offset + 4], byteorder='little', signed=False)

                if self._off_x >= 0: x = read_long(self._off_x)
                if self._off_y >= 0: y = read_long(self._off_y)
                if self._off_p >= 0: p = read_uint(self._off_p)

                raw_data = (x, y, p)

                try:
                    self._queue.put_nowait(raw_data)
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                        self._queue.put_nowait(raw_data)
                    except (queue.Empty, queue.Full):
                        pass
            return 0

        return _user32.DefWindowProcW(hwnd, msg, wParam, lParam)

    def _msg_loop(self):
        msg = MSG()
        while not self._stop.is_set():
            res = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if res <= 0: break
            if self._stop.is_set(): break
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    @staticmethod
    def _norm(axis: AXIS, v: int) -> float:
        lo, hi = int(axis.axMin), int(axis.axMax)
        if hi == lo: return 0.0
        f = (v - lo) / float(hi - lo)
        return max(0.0, min(1.0, f))

    def _ema(self, prev, new):
        if new is None or prev is None: return new
        a = float(self._smooth_alpha)
        return (1 - a) * prev + a * new


@WNDPROC
def _global_wndproc(hwnd, msg, wParam, lParam):
    try:
        inst = _instances.get(hwnd)
        if inst:
            return inst._handle_msg(hwnd, msg, wParam, lParam)
    except Exception:
        pass
    return _user32.DefWindowProcW(hwnd, msg, wParam, lParam)