#!/usr/bin/env python3
import sys, logging, time, os, math
from pathlib import Path

try:
    import curses

    HAS_CURSES = True
except Exception:
    HAS_CURSES = False

import rtde.rtde as rtde
import rtde.rtde_config as rtde_config

# ------------------- Config -------------------
ROBOT_HOST = os.environ.get("RTDE_HOST", "localhost")
ROBOT_PORT = 30004
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Point this to your XML config file
DEFAULT_CONFIG = PROJECT_ROOT / "RTDE_Configs" / "control_loop_configuration.xml"
CONFIG_XML = str(Path(os.environ.get("RTDE_CONFIG", str(DEFAULT_CONFIG))).resolve())

# Control settings
REFRESH_HZ = 50  # UI Refresh
CONTROL_HZ = 125  # Streaming Freq (Must match servoj 't' parameter roughly)
POS_STEP = 0.010  # m
ROT_STEP = 0.05  # rad

HOME_POSE = [-0.14397, -0.43562, 0.14627, .001, -3.166, -0.040]

logging.getLogger().setLevel(logging.INFO)


# ---- Quaternion Math (Critical for Smooth Rotation) ----
class RotationHelper:
    @staticmethod
    def axis_angle_to_quat(rx, ry, rz):
        angle = math.sqrt(rx * rx + ry * ry + rz * rz)
        if angle < 1e-6: return [1.0, 0.0, 0.0, 0.0]
        s = math.sin(angle / 2) / angle
        return [math.cos(angle / 2), rx * s, ry * s, rz * s]

    @staticmethod
    def quat_to_axis_angle(q):
        w, x, y, z = q
        norm = math.sqrt(w * w + x * x + y * y + z * z)
        if norm > 0: w, x, y, z = w / norm, x / norm, y / norm, z / norm
        angle = 2 * math.acos(max(-1.0, min(1.0, w)))
        s = math.sqrt(1 - w * w)
        if s < 1e-6: return [0.0, 0.0, 0.0]
        f = angle / s
        return [x * f, y * f, z * f]

    @staticmethod
    def slerp(q1, q2, t):
        w1, x1, y1, z1 = q1
        w2, x2, y2, z2 = q2
        dot = w1 * w2 + x1 * x2 + y1 * y2 + z1 * z2
        if dot < 0.0:
            w2, x2, y2, z2 = -w2, -x2, -y2, -z2
            dot = -dot
        if dot > 0.9995:
            k0, k1 = 1.0 - t, t
        else:
            theta_0 = math.acos(dot)
            sin_theta = math.sin(theta_0 * t)
            sin_theta_0 = math.sin(theta_0)
            k0 = math.cos(theta_0 * t) - dot * sin_theta / sin_theta_0
            k1 = sin_theta / sin_theta_0
        return [w1 * k0 + w2 * k1, x1 * k0 + x2 * k1, y1 * k0 + y2 * k1, z1 * k0 + z2 * k1]


# ---- Functions ----

def list_to_setp(sp, lst):
    for i in range(6):
        setattr(sp, f"input_double_register_{i}", float(lst[i]))
    return sp


def clamp_pose(p):
    x, y, z, rx, ry, rz = p
    x = max(-1.5, min(1.5, x))
    y = max(-1.5, min(1.5, y))
    z = max(-0.2, min(1.5, z))
    return [x, y, z, rx, ry, rz]


def plan_segments(start, goal, max_pos=0.005, max_rot=0.03):
    sx, sy, sz = start[0:3]
    gx, gy, gz = goal[0:3]

    dist_pos = math.sqrt((gx - sx) ** 2 + (gy - sy) ** 2 + (gz - sz) ** 2)

    q_start = RotationHelper.axis_angle_to_quat(*start[3:6])
    q_goal = RotationHelper.axis_angle_to_quat(*goal[3:6])
    dot = abs(sum([a * b for a, b in zip(q_start, q_goal)]))
    angle_diff = 2 * math.acos(max(-1.0, min(1.0, dot)))

    steps = max(1, int(math.ceil(dist_pos / max_pos)), int(math.ceil(angle_diff / max_rot)))
    segs = []
    for i in range(1, steps + 1):
        t = i / steps
        lx, ly, lz = sx + (gx - sx) * t, sy + (gy - sy) * t, sz + (gz - sz) * t
        q_curr = RotationHelper.slerp(q_start, q_goal, t)
        rx, ry, rz = RotationHelper.quat_to_axis_angle(q_curr)
        segs.append([lx, ly, lz, rx, ry, rz])
    return [clamp_pose(s) for s in segs]


def run_loop(io, interactive=False):
    # Setup RTDE
    conf = rtde_config.ConfigFile(CONFIG_XML)
    state_names, state_types = conf.get_recipe("state")
    setp_names, setp_types = conf.get_recipe("setp")
    watchdog_names, watchdog_types = conf.get_recipe("watchdog")

    con = rtde.RTDE(ROBOT_HOST, ROBOT_PORT)
    io.write_lines([f"Connecting to {ROBOT_HOST}..."])
    try:
        con.connect()
        con.get_controller_version()
    except Exception:
        io.write_lines(["Connection Failed! Is URSim running?"])
        time.sleep(2)
        return

    con.send_output_setup(state_names, state_types)
    setp = con.send_input_setup(setp_names, setp_types)
    watchdog = con.send_input_setup(watchdog_names, watchdog_types)

    if not con.send_start():
        io.write_lines(["RTDE Start Failed. Is the URP program running?"])
        return

    # Initialize State
    desired = list(HOME_POSE)
    current_cmd = list(desired)

    # Send initial Home pose
    list_to_setp(setp, desired)
    watchdog.input_int_register_0 = 1  # SIGNAL ROBOT TO MOVE
    con.send(setp)
    con.send(watchdog)

    segment_queue = []
    dt = 1.0 / CONTROL_HZ
    next_loop = time.perf_counter()

    io.write_lines(["Connected! Use Arrow Keys/WASD to move."])

    try:
        while io.is_alive():
            t_start = time.perf_counter()

            # 1. Input
            dirty = False
            x, y, z, rx, ry, rz = desired

            if interactive:
                key = io.read_key()
                if key != -1:
                    # Clear queue for responsiveness
                    if len(segment_queue) > 0:
                        current_cmd = segment_queue[0]
                        segment_queue = []

                    if key == getattr(curses, "KEY_RIGHT", 10000):
                        x += POS_STEP; dirty = True
                    elif key == getattr(curses, "KEY_LEFT", 10001):
                        x -= POS_STEP; dirty = True
                    elif key == getattr(curses, "KEY_UP", 10002):
                        y += POS_STEP; dirty = True
                    elif key == getattr(curses, "KEY_DOWN", 10003):
                        y -= POS_STEP; dirty = True
                    elif key == getattr(curses, "KEY_PPAGE", 10004):
                        z += POS_STEP; dirty = True
                    elif key == getattr(curses, "KEY_NPAGE", 10005):
                        z -= POS_STEP; dirty = True
                    elif key in (ord('w'), ord('W')):
                        rx += ROT_STEP; dirty = True
                    elif key in (ord('s'), ord('S')):
                        rx -= ROT_STEP; dirty = True
                    elif key in (ord('a'), ord('A')):
                        ry += ROT_STEP; dirty = True
                    elif key in (ord('d'), ord('D')):
                        ry -= ROT_STEP; dirty = True
                    elif key in (ord('q'), ord('Q')):
                        rz += ROT_STEP; dirty = True
                    elif key in (ord('e'), ord('E')):
                        rz -= ROT_STEP; dirty = True
                    elif key in (ord('g'), ord('G')):
                        x, y, z, rx, ry, rz = HOME_POSE; dirty = True
                    elif key == 27:
                        break

            if dirty:
                desired = clamp_pose([x, y, z, rx, ry, rz])
                segment_queue = plan_segments(current_cmd, desired)

            # 2. Output to Robot
            if segment_queue:
                next_p = segment_queue.pop(0)
            else:
                next_p = desired

            list_to_setp(setp, next_p)
            con.send(setp)

            # Keep Watchdog High
            watchdog.input_int_register_0 = 1
            con.send(watchdog)

            current_cmd = next_p

            # 3. UI
            if interactive and (t_start % (1.0 / REFRESH_HZ) < dt):
                io.write_lines([
                    "RTDE Streaming Mode (125Hz)",
                    f"Tgt: {['%.3f' % v for v in desired]}",
                    f"Queue: {len(segment_queue)} | Loop: {(time.perf_counter() - t_start) * 1000:.1f}ms"
                ])

            # 4. Sleep
            now = time.perf_counter()
            sleep_time = next_loop - now
            if sleep_time > 0:
                time.sleep(sleep_time)
            next_loop += dt

    except KeyboardInterrupt:
        pass
    finally:
        watchdog.input_int_register_0 = 0
        try:
            con.send(watchdog)
        except:
            pass
        con.disconnect()


# --- IO Classes (Standard) ---
class CursesIO:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(0)
        stdscr.nodelay(True)

    def read_key(self):
        try:
            return self.stdscr.getch()
        except:
            return -1

    def write_lines(self, lines):
        self.stdscr.erase()
        for i, l in enumerate(lines):
            try:
                self.stdscr.addstr(i, 0, l)
            except:
                pass
        self.stdscr.refresh()

    def is_alive(self):
        return True


class PrintIO:
    def read_key(self): return -1

    def write_lines(self, lines):
        print("\n" * 50)
        for l in lines: print(l)

    def is_alive(self): return True


def main():
    if HAS_CURSES and sys.stdout.isatty():
        curses.wrapper(lambda s: run_loop(CursesIO(s), True))
    else:
        run_loop(PrintIO(), False)


if __name__ == "__main__":
    main()