#!/usr/bin/env python3
import sys, time, os, math
from pathlib import Path

# ---- Import Tablet Reader ----
try:
    from tablet_reader import TabletReader
except ImportError:
    print("CRITICAL: Could not import 'tablet_reader.py'.")
    print("Ensure tablet_reader.py and wintab_wrapper.py are in this folder.")
    sys.exit(1)

import rtde.rtde as rtde
import rtde_config

# ------------------- Config -------------------
ROBOT_HOST = os.environ.get("RTDE_HOST", "localhost")
ROBOT_PORT = 30004
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "RTDE_Configs" / "control_loop_configuration.xml"
CONFIG_XML = str(Path(os.environ.get("RTDE_CONFIG", str(DEFAULT_CONFIG))).resolve())

# ---- DIMENSIONS (METERS) ----
# Width (Left/Right) = 8 inches
# Height (Out/In) = 5 inches
TABLET_WIDTH_M = 0.2032
TABLET_HEIGHT_M = 0.127

# Home Pose [x, y, z, rx, ry, rz]
# This is the "Center" of the pad in robot space
HOME_POSE = [-0.14397, -0.43562, 0.14627, .001, -3.166, -0.040]

CONTROL_HZ = 125.0


# ----------------------------------------------

def list_to_setp(sp, lst):
    for i in range(6):
        setattr(sp, f"input_double_register_{i}", float(lst[i]))
    return sp


def map_tablet_to_robot(tab_x, tab_y, center_pose):
    """
    Maps normalized tablet (0.0 - 1.0) to Robot Absolute Position.
    """
    cx, cy, cz, crx, cry, crz = center_pose

    x_offset = (0.5 - tab_x) * TABLET_WIDTH_M
    rx = cx + x_offset

    y_offset = (0.5 - tab_y) * TABLET_HEIGHT_M
    ry = cy + y_offset

    return [rx, ry, cz, crx, cry, crz]


def run_wacom_loop():
    # 1. Setup Tablet
    print("Initializing Wacom Tablet...")
    try:
        # smooth_alpha=0.15 gives a good balance of lag vs jitter
        tablet = TabletReader(normalize=True, smooth_alpha=0.2)
        tablet.start()
    except Exception as e:
        print(f"Failed to start tablet: {e}")
        return

    # 2. Setup RTDE
    print(f"Connecting to Robot at {ROBOT_HOST}...")
    conf = rtde_config.ConfigFile(CONFIG_XML)
    state_names, state_types = conf.get_recipe("state")
    setp_names, setp_types = conf.get_recipe("setp")
    watchdog_names, watchdog_types = conf.get_recipe("watchdog")

    con = rtde.RTDE(ROBOT_HOST, ROBOT_PORT)
    try:
        con.connect()
        con.get_controller_version()
    except Exception:
        print("RTDE Connection Failed! Is URSim running?")
        tablet.stop()
        return

    con.send_output_setup(state_names, state_types)
    setp = con.send_input_setup(setp_names, setp_types)
    watchdog = con.send_input_setup(watchdog_names, watchdog_types)

    if not con.send_start():
        print("RTDE Start Failed. Is the URP program running?")
        tablet.stop()
        return

    # 3. Initialize Robot State
    current_cmd = list(HOME_POSE)
    list_to_setp(setp, current_cmd)
    watchdog.input_int_register_0 = 1
    con.send(setp)
    con.send(watchdog)

    print("Control Active!")
    print(f"   Mapping: 8x5\" Box around {HOME_POSE[:2]}")
    print("   Pen Top    -> Robot Back")
    print("   Pen Bottom -> Robot Front")
    print("   Lift pen to Hold Position.")

    dt = 1.0 / CONTROL_HZ
    next_loop = time.perf_counter()

    try:
        while True:
            # 4. Read Tablet
            try:
                # 2ms timeout for high responsiveness
                tx, ty, tp = tablet.read_normalized(timeout=0.002)

                # Map coordinates
                target_pose = map_tablet_to_robot(tx, ty, HOME_POSE)
                current_cmd = target_pose
                status = f"ON : X={tx:.2f} Y={ty:.2f}"

            except TimeoutError:
                # Pen lifted: Hold last position
                status = "OFF: Holding..."

            # 5. Send to Robot
            list_to_setp(setp, current_cmd)
            con.send(setp)
            con.send(watchdog)

            # 6. Print Status
            if time.time() % 0.5 < 0.05:
                sys.stdout.write(f"\r{status} | Rob: [{current_cmd[0]:.3f}, {current_cmd[1]:.3f}]")
                sys.stdout.flush()

            # 7. Sync Loop
            now = time.perf_counter()
            sleep_time = next_loop - now
            if sleep_time > 0:
                time.sleep(sleep_time)
            next_loop += dt

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        tablet.stop()
        watchdog.input_int_register_0 = 0
        try:
            con.send(watchdog)
        except:
            pass
        con.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    run_wacom_loop()