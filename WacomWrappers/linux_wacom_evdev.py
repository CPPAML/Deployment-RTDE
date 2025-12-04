# pip install evdev
import threading
import time
from typing import Optional, Tuple
from evdev import InputDevice, ecodes, list_devices

class WacomTabletReader:
    """
    Read x, y, and pressure from a Wacom tablet via linux input (evdev).

    Features:
      - Auto-discovers a tablet if device_path is not provided.
      - Normalizes x, y, pressure to 0..1 (optional).
      - Lightweight smoothing to reduce jitter (optional).
      - Thread-safe: a background reader thread updates latest state.

    Usage:
      reader = WacomTabletReader(normalize=True, smooth_alpha=0.2)
      reader.start()
      try:
          while True:
              x, y, p = reader.read()  # latest values (floats if normalize=True)
              # ... send to the robot here ...
              time.sleep(0.01)  # 100 Hz loop
      finally:
          reader.stop()
    """
    def __init__(self,
                 device_path: Optional[str] = None,
                 normalize: bool = True,
                 smooth_alpha: Optional[float] = 0.2,
                 require_wacom_name: bool = False):
        """
        device_path: e.g. '/dev/input/eventX'. If None, tries to auto-detect.
        normalize: map x,y,pressure to 0..1 using device absinfo ranges.
        smooth_alpha: 0..1 for EMA smoothing (None disables).
        require_wacom_name: if True, only pick devices whose name contains 'wacom'.
        """
        self.device_path = device_path
        self.normalize = normalize
        self.smooth_alpha = smooth_alpha
        self.require_wacom_name = require_wacom_name

        self.dev: Optional[InputDevice] = None
        self.thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

        # raw integer space and normalized/smoothed state
        self._abs_info = {}  # code -> AbsInfo (min, max, etc.)
        self._x = None
        self._y = None
        self._p = None
        self._x_s = None
        self._y_s = None
        self._p_s = None

    # ---------- public API ----------

    def start(self):
        """Open the device and start background event reader."""
        if self.dev is None:
            self.dev = self._open_device()
            self._cache_abs_info()

        self._running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop background reader and close device."""
        self._running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.dev:
            try:
                self.dev.close()
            except Exception:
                pass
        self.dev = None

    def read(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Return the latest (x, y, pressure).
        - If normalize=True, values are floats in [0,1].
        - Otherwise raw integer units from the device.
        Values may be None until first events arrive.
        """
        with self._lock:
            if self.normalize:
                return self._x_s, self._y_s, self._p_s
            else:
                return self._x, self._y, self._p

    # ---------- internals ----------

    def _open_device(self) -> InputDevice:
        if self.device_path:
            return InputDevice(self.device_path)

        # Auto-discover: prefer devices that have ABS_X, ABS_Y, ABS_PRESSURE
        candidates = []
        for path in list_devices():
            dev = InputDevice(path)
            try:
                caps = dev.capabilities(verbose=True)
            except Exception:
                continue

            ev_abs = any(c for c in caps if c[0] == ecodes.EV_ABS)
            ev_key = any(c for c in caps if c[0] == ecodes.EV_KEY)
            has_x = self._has_abs(caps, ecodes.ABS_X)
            has_y = self._has_abs(caps, ecodes.ABS_Y)
            has_p = self._has_abs(caps, ecodes.ABS_PRESSURE)

            name_ok = True
            if self.require_wacom_name:
                name_ok = ("wacom" in (dev.name or "").lower())

            if ev_abs and ev_key and has_x and has_y and has_p and name_ok:
                # Prefer ones whose name contains 'wacom'
                priority = 0 if "wacom" in (dev.name or "").lower() else 1
                candidates.append((priority, path, dev))

        if not candidates:
            raise RuntimeError(
                "No suitable tablet device found. "
                "Pass device_path explicitly (e.g. /dev/input/eventX)."
            )
        candidates.sort(key=lambda x: x[0])
        return InputDevice(candidates[0][1])

    @staticmethod
    def _has_abs(caps, code) -> bool:
        for etype, items in caps:
            if etype == ecodes.EV_ABS:
                for it in items:
                    if isinstance(it, tuple) and it[0] == code:
                        return True
        return False

    def _cache_abs_info(self):
        # Save AbsInfo for normalization
        for code in (ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_PRESSURE):
            try:
                self._abs_info[code] = self.dev.absinfo(code)
            except Exception:
                self._abs_info[code] = None

    def _loop(self):
        # Read events and update latest state
        for event in self.dev.read_loop():
            if not self._running:
                break
            if event.type != ecodes.EV_ABS:
                continue

            updated = False
            if event.code == ecodes.ABS_X:
                with self._lock:
                    self._x = event.value
                    updated = True
            elif event.code == ecodes.ABS_Y:
                with self._lock:
                    self._y = event.value
                    updated = True
            elif event.code == ecodes.ABS_PRESSURE:
                with self._lock:
                    self._p = event.value
                    updated = True

            if updated:
                self._apply_norm_and_smooth()

    def _norm(self, code, val):
        if val is None:
            return None
        info = self._abs_info.get(code)
        if not info:
            return None
        # Some devices report min != 0, so normalize against [min,max]
        lo = info.min
        hi = info.max
        if hi == lo:
            return 0.0
        v = (val - lo) / float(hi - lo)
        # Clamp to [0,1] to be safe
        return 0.0 if v < 0 else 1.0 if v > 1 else v

    def _ema(self, prev, new):
        if new is None:
            return prev
        if prev is None:
            return new
        a = float(self.smooth_alpha)
        return (1 - a) * prev + a * new

    def _apply_norm_and_smooth(self):
        with self._lock:
            if self.normalize:
                x = self._norm(ecodes.ABS_X, self._x)
                y = self._norm(ecodes.ABS_Y, self._y)
                p = self._norm(ecodes.ABS_PRESSURE, self._p)
            else:
                x, y, p = self._x, self._y, self._p

            if self.smooth_alpha is not None:
                self._x_s = self._ema(self._x_s if self.normalize else self._x, x)
                self._y_s = self._ema(self._y_s if self.normalize else self._y, y)
                self._p_s = self._ema(self._p_s if self.normalize else self._p, p)
            else:
                self._x_s, self._y_s, self._p_s = x, y, p

# ---------------- Example ----------------
if __name__ == "__main__":
    reader = WacomTabletReader(normalize=True, smooth_alpha=0.15)
    reader.start()
    try:
        while True:
            x, y, p = reader.read()
            # x,y,p are None until the first events arrive
            if x is not None:
                print(f"x={x:.3f}, y={y:.3f}, p={p:.3f}")
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        reader.stop()
