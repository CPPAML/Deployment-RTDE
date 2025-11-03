# tablet_reader.py
# Cross-platform tablet reader that auto-selects a backend:
#  - Windows: WinTab/ctypes
#  - Linux:   evdev
#
# Public API:
#   reader = TabletReader(normalize=True, smooth_alpha=0.12)
#   reader.start()
#   x,y,p = reader.read_normalized(timeout=1.0)  # floats in [0,1]
#   xr,yr,pr = reader.read_raw(timeout=1.0)      # raw backend units
#   reader.stop()

from __future__ import annotations
import sys
import time
from typing import Optional, Tuple

# ---- choose backend by platform ----
if sys.platform.startswith("win"):
    try:
        from wintab_wrapper import Tablet as _WinTabTablet  # <-- your file exposing Tablet
    except ImportError as e:
        raise ImportError(
            "Couldn't import wintab_wrapper.Tablet. "
            "Place your Windows backend in 'wintab_wrapper.py' (exports Tablet), "
            "or adjust the import here."
        )


    class _Backend:
        def __init__(self, normalize: bool = True, smooth_alpha: Optional[float] = 0.12, **_):
            # WinTab Tablet already exposes normalized & raw readers
            self._t = _WinTabTablet(smooth_alpha=smooth_alpha)
            self._normalize = normalize

        def start(self): self._t.start()
        def stop(self): self._t.stop()

        def read_normalized(self, timeout: Optional[float]) -> Tuple[float, float, float]:
            # (x,y,p) in [0,1]
            return self._t.read_normalized(timeout=timeout)

        def read_raw(self, timeout: Optional[float]) -> Tuple[int, int, int]:
            # raw integer device space
            return self._t.read(timeout=timeout)

elif sys.platform.startswith("linux"):
    try:
        from linux_wacom_evdev import WacomTabletReader as _EvdevTablet
    except ImportError as e:
        raise ImportError(
            "Couldn't import linux_wacom_evdev.WacomTabletReader. "
            "Place your Linux backend in 'linux_wacom_evdev.py' (exports WacomTabletReader), "
            "or adjust the import here."
        )
    class _Backend:
        def __init__(self,
                     normalize: bool = True,
                     smooth_alpha: Optional[float] = 0.15,
                     device_path: Optional[str] = None,
                     require_wacom_name: bool = False,
                     **_):
            # The evdev backend can emit normalized or raw depending on ctor flag
            self._normalize = normalize
            self._t = _EvdevTablet(
                device_path=device_path,
                normalize=normalize,
                smooth_alpha=smooth_alpha,
                require_wacom_name=require_wacom_name,
            )
            self._last: Tuple[Optional[float], Optional[float], Optional[float]] = (None, None, None)

        def start(self): self._t.start()
        def stop(self): self._t.stop()

        def _read_with_timeout(self, timeout: Optional[float]):
            deadline = (time.time() + timeout) if timeout else None
            while True:
                x, y, p = self._t.read()
                if x is not None and y is not None and p is not None:
                    return x, y, p
                if deadline is not None and time.time() >= deadline:
                    return x, y, p  # may be None if nothing arrived yet
                time.sleep(0.005)

        def read_normalized(self, timeout: Optional[float]) -> Tuple[float, float, float]:
            # If constructed with normalize=True (default), values are already 0..1
            x, y, p = self._read_with_timeout(timeout)
            return x, y, p  # either floats 0..1 or raw if normalize=False

        def read_raw(self, timeout: Optional[float]):
            # Only guaranteed "raw" if the backend was created with normalize=False
            if self._normalize:
                raise RuntimeError(
                    "Linux backend is in normalize=True mode. "
                    "Construct TabletReader(normalize=False) to get raw values."
                )
            return self._read_with_timeout(timeout)

else:
    raise RuntimeError(f"Unsupported OS: {sys.platform}")


class TabletReader:
    """
    Cross-platform tablet reader with a unified API.

    Args:
      normalize: if True, returns x,y,p in [0,1]. If False, returns backend raw units.
      smooth_alpha: EMA smoothing factor (backend dependent; 0..1; None disables)
      device_path (Linux): override /dev/input/eventX
      require_wacom_name (Linux): only match devices with 'wacom' in their name

    Methods:
      start(), stop()
      read_normalized(timeout=None) -> (x,y,p) floats in [0,1]
      read_raw(timeout=None)        -> raw backend units
    """
    def __init__(self,
                 normalize: bool = True,
                 smooth_alpha: Optional[float] = 0.12,
                 device_path: Optional[str] = None,
                 require_wacom_name: bool = False):
        self._backend = _Backend(
            normalize=normalize,
            smooth_alpha=smooth_alpha,
            device_path=device_path,
            require_wacom_name=require_wacom_name,
        )
        self._normalize = normalize

    def start(self): self._backend.start()
    def stop(self): self._backend.stop()

    def read_normalized(self, timeout: Optional[float] = None):
        """Always returns (x,y,p) in [0,1]; on Linux this requires normalize=True at construction."""
        vals = self._backend.read_normalized(timeout)
        if vals[0] is None:
            raise TimeoutError("No tablet data available yet (normalized). Try increasing timeout or ensure pen is in proximity.")
        # Windows: guaranteed 0..1. Linux: 0..1 if normalize=True; else raw (documented).
        return vals

    def read_raw(self, timeout: Optional[float] = None):
        """Returns raw device units; on Linux this requires normalize=False at construction."""
        vals = self._backend.read_raw(timeout)
        if vals[0] is None:
            raise TimeoutError("No tablet data available yet (raw). Try increasing timeout or ensure pen is in proximity.")
        return vals


# -------------- example --------------
if __name__ == "__main__":
    # Normalized control (recommended for robot mapping)
    reader = TabletReader(normalize=True, smooth_alpha=0.12)
    reader.start()
    try:
        while True:
            x, y, p = reader.read_normalized(timeout=2.0)
            print(f"x={x:.3f}  y={y:.3f}  p={p:.3f}")
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        reader.stop()
