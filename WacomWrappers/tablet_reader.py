# tablet_reader.py
# Cross-platform tablet reader.

from __future__ import annotations
import sys
import threading
import time
import queue
import traceback
from typing import Optional, Tuple

# ---- choose backend by platform ----
if sys.platform.startswith("win"):
    try:
        try:
            from .wintab_wrapper import Tablet as _WinTabTablet, WintabError
        except ImportError:
            from wintab_wrapper import Tablet as _WinTabTablet, WintabError
    except ImportError as e:
        print("CRITICAL ERROR: Could not import wintab_wrapper.")
        raise ImportError(
            "Couldn't import wintab_wrapper.Tablet. "
            "Ensure 'wintab_wrapper.py' is in the same folder."
        ) from e


    class _Backend:
        def __init__(self, normalize: bool = True, smooth_alpha: Optional[float] = 0.12, **_):
            print("[Backend] Initializing WintabTablet...")
            self._t = _WinTabTablet(smooth_alpha=smooth_alpha)
            self._normalize = normalize

        def start(self, wait_ready: bool = True, timeout: float = 3.0):
            print("[Backend] Starting WintabTablet...")
            self._t.start(wait_ready=wait_ready, timeout=timeout)

        def stop(self):
            print("[Backend] Stopping WintabTablet...")
            self._t.stop()

        def read_normalized(self, timeout: Optional[float]) -> Tuple[float, float, float]:
            try:
                return self._t.read_normalized(timeout=timeout)
            except (WintabError, queue.Empty):
                # Return None tuple to signal Timeout in Reader
                return (None, None, None)

        def read_raw(self, timeout: Optional[float]) -> Tuple[int, int, int]:
            try:
                return self._t.read(timeout=timeout)
            except (WintabError, queue.Empty):
                return (None, None, None)
else:
    raise RuntimeError(f"Unsupported OS: {sys.platform}")


class TabletReader:
    def __init__(self, normalize: bool = True, smooth_alpha: Optional[float] = 0.12, **kwargs):
        self._backend = _Backend(normalize=normalize, smooth_alpha=smooth_alpha, **kwargs)

    def start(self):
        self._backend.start()

    def stop(self):
        self._backend.stop()

    def read_normalized(self, timeout: Optional[float] = None):
        vals = self._backend.read_normalized(timeout)
        if vals is None or vals[0] is None:
            raise TimeoutError("No tablet data (pen likely away)")
        return vals

    def read_raw(self, timeout: Optional[float] = None):
        vals = self._backend.read_raw(timeout)
        if vals is None or vals[0] is None:
            raise TimeoutError("No tablet data (pen likely away)")
        return vals


# -------------- example --------------
if __name__ == "__main__":
    reader = TabletReader(normalize=True, smooth_alpha=0.12)
    print("Starting tablet listener...")
    try:
        reader.start()
        print("Tablet started. Bring pen close (Ctrl+C to stop)...")

        while True:
            try:
                # Set a small timeout for responsiveness
                x, y, p = reader.read_normalized(timeout=0.1)

                status = "Active " if p > 0 else "Hover  "
                print(f"[{status}] x={x:.3f}  y={y:.3f}  p={p:.3f}")

            except TimeoutError:
                # Print a dot so you know the script hasn't crashed
                sys.stdout.write(".")
                sys.stdout.flush()

            except Exception as e:
                pass  # Ignore loops errors

    except KeyboardInterrupt:
        print("\nStopping...")
    except Exception as e:
        print(f"\n[Fatal Error]: {e}")
        traceback.print_exc()
    finally:
        reader.stop()
        print("Done.")