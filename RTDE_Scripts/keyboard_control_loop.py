#!/usr/bin/env python3
import sys, logging, time, os, math
from pathlib import Path

# Attempt to import curses lazily and safely
try:
    import curses  # only used if terminal is available
    HAS_CURSES = True
except Exception:
    HAS_CURSES = False

import rtde.rtde as rtde
import rtde.rtde_config as rtde_config

# ------------------- Config -------------------
ROBOT_HOST = "localhost"     # If running Python inside another container, use "host.docker.internal"
ROBOT_PORT = 30004
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "RTDE_Configs" / "control_loop_configuration.xml"

CONFIG_XML = str(Path(os.environ.get("RTDE_CONFIG", str(DEFAULT_CONFIG))).resolve())

POS_STEP_DEFAULT = 0.010     # meters per keypress
ROT_STEP_DEFAULT = 0.05      # radians per keypress (~2.9 deg)
REFRESH_HZ = 50              # UI refresh rate (curses mode)
PRINT_HZ = 2                 # Print rate (non-curses mode)
# Singularity guard constants (UR wrist 2 near 0 rad)
WRIST2_WARN = 0.25   # rad (~14°)
WRIST2_LIMIT = 0.10  # rad (~6°)
TILT_STEP = 0.07     # rad added when too close
MIN_SEG = 0.002      # m, smaller segments near singularity
# Home pose (x(m), y(m), z(m), xq(rads), yq(rads), zq(rads))
HOME_POSE = [-0.14397, -0.43562, 0.20203, 0.001, -3.116, -0.040]
# ----------------------------------------------

logging.getLogger().setLevel(logging.INFO)

def setp_to_list(sp):
    return [getattr(sp, f"input_double_register_{i}") for i in range(6)]

def list_to_setp(sp, lst):
    for i in range(6):
        setattr(sp, f"input_double_register_{i}", float(lst[i]))
    return sp

def clamp_pose(p):
    # Soft clamps in METERS for demo; tweak as needed for your cell/sim
    x,y,z,rx,ry,rz = p
    x = max(-1.5, min(1.5, x))
    y = max(-1.5, min(1.5, y))
    z = max(-0.2, min(1.5, z))
    # Ensure rotational components remain within a sane bound (radians)
    if abs(rx) > 6.28319: rx = 0.0
    if abs(ry) > 6.28319: ry = 0.0
    if abs(rz) > 6.28319: rz = 0.0
    return [x,y,z,rx,ry,rz]

# ---- IK-friendly helpers -----------------------------------------------------

def plan_segments(start, goal, max_pos_step=0.005, max_rot_step=0.03):
    """Split a pose change into small linear waypoints.
    start, goal: [x,y,z,rx,ry,rz] in meters/radians.
    Returns a list of intermediate poses including the goal, excluding start.
    """
    sx,sy,sz,srx,sry,srz = start
    gx,gy,gz,grx,gry,grz = goal
    dp = [gx-sx, gy-sy, gz-sz]
    dr = [grx-srx, gry-sry, grz-srz]
    steps_pos = max(1, int(math.ceil(max(abs(dp[0]), abs(dp[1]), abs(dp[2])) / max_pos_step)))
    steps_rot = max(1, int(math.ceil(max(abs(dr[0]), abs(dr[1]), abs(dr[2])) / max_rot_step)))
    n = max(steps_pos, steps_rot)
    segs = []
    for i in range(1, n+1):
        t = i / float(n)
        segs.append([
            sx + dp[0]*t,
            sy + dp[1]*t,
            sz + dp[2]*t,
            srx + dr[0]*t,
            sry + dr[1]*t,
            srz + dr[2]*t,
        ])
    return [clamp_pose(s) for s in segs]

def run_control_loop(io, interactive=False):
    """
    io: object with methods:
        - read_key() -> int or -1
        - write_lines(list[str])
        - sleep(seconds)
        - is_alive() -> bool
    interactive: if True, reads keys to adjust pose; otherwise prints status only
    """
    conf = rtde_config.ConfigFile(CONFIG_XML)
    state_names, state_types = conf.get_recipe("state")
    setp_names, setp_types = conf.get_recipe("setp")
    watchdog_names, watchdog_types = conf.get_recipe("watchdog")

    con = rtde.RTDE(ROBOT_HOST, ROBOT_PORT)
    con.connect()
    con.get_controller_version()
    con.send_output_setup(state_names, state_types)
    setp = con.send_input_setup(setp_names, setp_types)
    watchdog = con.send_input_setup(watchdog_names, watchdog_types)

    # Start synchronization before trying to receive any state
    if not con.send_start():
        con.disconnect()
        raise SystemExit("RTDE send_start() failed – is the URP program playing?")

    # ---- Initialize desired pose in METERS/RADIANS ----
    # Prefer the live robot pose (already meters/radians) to avoid frame/unit mismatches.
    desired = None
    if "actual_TCP_pose" in state_names:
        # Wait briefly for the first state packet
        for _ in range(100):  # ~2 seconds at 50 Hz
            s = con.receive()
            if s is not None and hasattr(s, "actual_TCP_pose") and s.actual_TCP_pose:
                desired = list(s.actual_TCP_pose)
                break

    if desired is None:
        # Fallback to configured HOME pose (meters, radians)
        desired = list(HOME_POSE)

    list_to_setp(setp, desired)
    for i in range(6):
        setattr(setp, f"input_double_register_{i}", desired[i])
    watchdog.input_int_register_0 = 0
    # ---------------------------------------------------

    base_pos_step = POS_STEP_DEFAULT
    base_rot_step = ROT_STEP_DEFAULT
    pending_send = True           # send initial pose
    move_completed = True
    last_send_time = 0.0
    send_rate_limit = 0.02        # at most 50 Hz setpoint updates
    sync_request = False          # when True, sync commanded pose to current TCP

    # Helper to read q5 (wrist 2) safely
    def get_q5(s):
        q = getattr(s, 'actual_q', None) or getattr(s, 'target_q', None)
        return q[4] if q else None

    # IK-friendly streaming: maintain a queue of small waypoints
    current_cmd = list(desired)   # last pose we actually sent
    segment_queue = []            # pending small waypoints toward desired

    info = (
        "Use Arrows (X/Y), PgUp/PgDn (Z), W/S (Rx), A/D (Ry), Q/E (Rz), +/- change step. "
        "R:+5cm Z, F:-5cm Z, H:hover +10cm, C:sync to current TCP, G:home pose, B:branch flip, ESC quits. IK-safe streaming is enabled."
    )

    # Last known singularity scale for pre-key step sizing
    last_scale = 1.0

    try:
        while io.is_alive():
            dirty = False
            need_replan = False
            x,y,z,rx,ry,rz = desired

            # Use last known singularity scale for pre-key step sizing
            scale = 1.0
            try:
                scale = last_scale
            except NameError:
                last_scale = 1.0
                scale = 1.0
            pos_step_eff = base_pos_step * scale
            rot_step_eff = base_rot_step * scale

            if interactive:
                key = io.read_key()
                if key != -1:
                    # Arrow keys and others only available in curses; in non-curses this does nothing
                    try:
                        if key in (curses.KEY_LEFT, curses.KEY_RIGHT, curses.KEY_UP, curses.KEY_DOWN,
                                   curses.KEY_PPAGE, curses.KEY_NPAGE):
                            pass
                    except Exception:
                        pass

                    # Movement handling (meters / radians)
                    if key == getattr(curses, "KEY_RIGHT", 10000):   x += pos_step_eff; dirty = True
                    elif key == getattr(curses, "KEY_LEFT", 10001):  x -= pos_step_eff; dirty = True
                    elif key == getattr(curses, "KEY_UP", 10002):    y += pos_step_eff; dirty = True
                    elif key == getattr(curses, "KEY_DOWN", 10003):  y -= pos_step_eff; dirty = True
                    elif key == getattr(curses, "KEY_PPAGE", 10004): z += pos_step_eff; dirty = True
                    elif key == getattr(curses, "KEY_NPAGE", 10005): z -= pos_step_eff; dirty = True
                    elif key in (ord('+'),):
                        base_pos_step *= 1.25; base_rot_step *= 1.25
                        pos_step_eff = base_pos_step * scale; rot_step_eff = base_rot_step * scale
                    elif key in (ord('-'),):
                        base_pos_step /= 1.25; base_rot_step /= 1.25
                        pos_step_eff = base_pos_step * scale; rot_step_eff = base_rot_step * scale
                    elif key in (ord('w'), ord('W')): rx += rot_step_eff; dirty = True
                    elif key in (ord('s'), ord('S')): rx -= rot_step_eff; dirty = True
                    elif key in (ord('a'), ord('A')): ry += rot_step_eff; dirty = True
                    elif key in (ord('d'), ord('D')): ry -= rot_step_eff; dirty = True
                    elif key in (ord('q'), ord('Q')): rz += rot_step_eff; dirty = True
                    elif key in (ord('e'), ord('E')): rz -= rot_step_eff; dirty = True
                    elif key in (ord('b'), ord('B')):
                        rz += math.pi; dirty = True  # 180° branch flip around tool Z
                    elif key in (ord('r'), ord('R')):
                        z += 0.05; dirty = True  # quick +5cm
                    elif key in (ord('f'), ord('F')):
                        z -= 0.05; dirty = True  # quick -5cm
                    elif key in (ord('h'), ord('H')):
                        z += 0.10; dirty = True  # hover +10cm
                    elif key in (ord('c'), ord('C')):
                        sync_request = True
                    elif key in (ord('g'), ord('G')):
                        x, y, z, rx, ry, rz = HOME_POSE
                        dirty = True
                    elif key in (27,):  # ESC
                        break

            if dirty:
                desired = clamp_pose([x,y,z,rx,ry,rz])
                need_replan = True

            # Receive state
            state = con.receive()
            if state is None:
                io.write_lines(["No RTDE state (is the URP playing?) Press ESC to exit."])
                io.sleep(0.5)
                continue

            # Optional: sync commanded pose to current TCP when requested
            if sync_request and hasattr(state, "actual_TCP_pose") and state.actual_TCP_pose:
                desired = clamp_pose(list(state.actual_TCP_pose))
                current_cmd = list(desired)
                segment_queue = []
                pending_send = False
                sync_request = False

            # Singularity proximity and step scaling
            q5 = get_q5(state)
            scale = 1.0
            sing_info = ''
            if q5 is not None:
                d = abs(q5)
                if d < WRIST2_WARN:
                    if d <= WRIST2_LIMIT:
                        scale = 0.1
                        sing_info = f"WRIST2 near 0 (|q5|={d:.3f} rad): slowing + may auto-tilt"
                    else:
                        scale = max(0.2, (d - WRIST2_LIMIT) / (WRIST2_WARN - WRIST2_LIMIT))
                        sing_info = f"WRIST2 warn (|q5|={d:.3f} rad): scaling {scale:.2f}"
            # Effective steps this cycle and segment sizing
            pos_step_eff = base_pos_step * scale
            rot_step_eff = base_rot_step * scale
            last_scale = scale
            pos_seg = max(MIN_SEG, 0.005 * scale)
            rot_seg = max(0.02, 0.03 * scale)

            # Replan segments if needed
            if need_replan:
                segment_queue = plan_segments(current_cmd, desired, max_pos_step=pos_seg, max_rot_step=rot_seg)
                pending_send = True
                need_replan = False

            # Handshake and send
            ready = getattr(state, "output_int_register_0", 1) == 1  # default 1 if not present
            now = time.time()
            # If we have queued segments, keep pending_send true until exhausted
            if segment_queue:
                pending_send = True

            # Auto-tilt away from wrist singularity if translating in XY
            if pending_send and segment_queue and (q5 is not None) and abs(q5) <= WRIST2_LIMIT:
                next_pose_peek = segment_queue[0]
                dx = next_pose_peek[0] - current_cmd[0]
                dy = next_pose_peek[1] - current_cmd[1]
                dz = next_pose_peek[2] - current_cmd[2]
                if abs(dx) + abs(dy) > 3 * abs(dz):
                    # apply small pitch (ry) away from 0 to open wrist
                    x,y,z,rx,ry,rz = desired
                    ry += TILT_STEP if q5 >= 0 else -TILT_STEP
                    desired = clamp_pose([x,y,z,rx,ry,rz])
                    segment_queue = plan_segments(current_cmd, desired, max_pos_step=pos_seg, max_rot_step=rot_seg)

            if pending_send and ready and (now - last_send_time) >= send_rate_limit:
                # Choose next waypoint toward the goal
                next_pose = segment_queue.pop(0) if segment_queue else desired
                list_to_setp(setp, next_pose)
                con.send(setp)
                current_cmd = list(next_pose)
                watchdog.input_int_register_0 = 1
                con.send(watchdog)
                last_send_time = now
                pending_send = bool(segment_queue)  # keep streaming while queue not empty
                move_completed = False
            else:
                # keep watchdog ticking even when not sending a new setpoint
                con.send(watchdog)

            # Track move completion
            if not move_completed and getattr(state, "output_int_register_0", 0) == 0:
                move_completed = True
                watchdog.input_int_register_0 = 0

            # Output
            lines = []
            if interactive:
                lines.append(info)
            lines.append(f"Target pose [x y z rx ry rz] (m, rad): {['%.4f'%v for v in desired]}")
            lines.append(f"base_pos_step={base_pos_step:.4f} m | base_rot_step={base_rot_step:.3f} rad | eff_pos_step={pos_step_eff:.4f} m | eff_rot_step={rot_step_eff:.3f} rad")
            if q5 is not None:
                lines.append(f"q5={q5:.3f} rad | singularity_scale={scale:.2f}")
            if sing_info:
                lines.append(sing_info)
            lines.append(f"ready={int(ready)} | pending={int(pending_send)} | segments={len(segment_queue)}")
            if hasattr(state, "target_q"):
                lines.append(f"target_q: {['%.4f'%v for v in state.target_q]}")
            io.write_lines(lines)

            # Pace
            io.sleep(1.0/(REFRESH_HZ if interactive else PRINT_HZ))

    except KeyboardInterrupt:
        pass
    finally:
        try:
            con.send_pause()
        except Exception:
            pass
        con.disconnect()

# IO adapters
class CursesIO:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.keypad(True)

    def read_key(self):
        try:
            return self.stdscr.getch()
        except Exception:
            return -1

    def write_lines(self, lines):
        self.stdscr.erase()
        for i, line in enumerate(lines):
            try:
                self.stdscr.addstr(i, 0, line)
            except Exception:
                pass
        self.stdscr.refresh()

    def sleep(self, sec):
        time.sleep(sec)

    def is_alive(self):
        return True

class PrintIO:
    def __init__(self):
        self._last = 0

    def read_key(self):
        return -1

    def write_lines(self, lines):
        now = time.time()
        if now - self._last >= (1.0/PRINT_HZ - 1e-6):
            print("-----")
            for line in lines:
                print(line)
            self._last = now

    def sleep(self, sec):
        time.sleep(sec)

    def is_alive(self):
        return True

def terminal_available():
    # A terminal is considered available if stdout is a TTY and TERM is set to a known type
    if not sys.stdout.isatty():
        return False
    term = os.environ.get("TERM", "")
    return bool(term) and term.lower() not in ("unknown", "dumb")

def main():
    if HAS_CURSES and terminal_available():
        curses.wrapper(lambda stdscr: run_control_loop(CursesIO(stdscr), interactive=True))
    else:
        print("No interactive terminal detected; running in non-curses mode.")
        print("Tip: run in a real terminal to use keyboard controls.")
        run_control_loop(PrintIO(), interactive=False)

if __name__ == "__main__":
    main()
