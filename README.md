# Deployment-RTDE

A starter for working with Universal Robots via RTDE plus optional Wacom tablet input.

This repo packages:
- A vendored UR RTDE Python client library (installed in editable mode).
- Ready-to-run example scripts to stream setpoints, record data, and plot.
- Cross‑platform Wacom tablet wrappers (Windows WinTab, Linux evdev) for interactive control.
- Helper scripts to set up your Python environment and to spin up URSim in Docker.

If you follow the steps below, you should be able to set up the environment, run URSim or connect to a real UR robot, and try the basic control/recording scripts.


## Contents
- Prerequisites (per OS)
- Install Docker via Command Line (Windows & Linux)
- Quick Start (per OS)
- Running URSim in Docker
- Connecting to a real robot
- Running the example scripts
- Tablet input (Windows/Linux)
- Configuration files
- Troubleshooting and FAQ


## Prerequisites

General
- Git and a clone of this repo.
- Internet access to pull Docker images and Python packages.

Windows
- Anaconda or Miniconda.
- PowerShell (Run scripts with “Run with PowerShell” or from a PS terminal).
- Docker Desktop with Linux containers enabled (for URSim).
- Optional: Wacom tablet + drivers that expose `Wintab32.dll` (see Tablet notes below).

Linux (Ubuntu/Debian recommended)
- Miniconda or Anaconda. Alternatively, Python 3.13 with venv.
- Docker Engine (for URSim) and permission to run Docker as your user.
- Optional: Wacom tablet; `evdev` Python package; read access to `/dev/input/event*`.

macOS
- Miniconda or Anaconda. Alternatively, Python 3.13 with venv.
- Docker Desktop (for URSim).
- Tablet backends provided here are Windows/Linux only; macOS can still run the RTDE scripts.


## Install Docker via Command Line (Windows & Linux)

Windows (PowerShell)
1) Ensure WSL2 is installed and enabled (Windows 10/11):
   ```powershell
   wsl --install
   # If prompted, restart Windows after installation
   ```
2) Install Docker Desktop via winget:
   ```powershell
   winget install -e --id Docker.DockerDesktop
   ```
3) Start Docker Desktop (first launch finalizes setup) and switch it to use Linux containers (default). Then verify:
   ```powershell
   Start-Process "$Env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
   docker --version
   docker run --rm hello-world
   ```
   If `docker` isn’t recognized after install, log out/in or reboot once.

Linux (Ubuntu/Debian)
1) Remove older Docker packages (if any):
   ```bash
   sudo apt-get remove -y docker docker-engine docker.io containerd runc || true
   ```
2) Set up Docker’s official apt repository:
   ```bash
   sudo apt-get update
   sudo apt-get install -y ca-certificates curl gnupg
   sudo install -m 0755 -d /etc/apt/keyrings
   curl -fsSL https://download.docker.com/linux/$(. /etc/os-release; echo "$ID")/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
   echo \
     "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$(. /etc/os-release; echo "$ID") \
     $(. /etc/os-release; echo "$VERSION_CODENAME") stable" | \
     sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
   sudo apt-get update
   ```
3) Install Docker Engine, CLI, and Compose plugin:
   ```bash
   sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
   ```
4) (Recommended) Run Docker as non-root:
   ```bash
   sudo usermod -aG docker "$USER"
   newgrp docker <<<'refresh groups in this shell'
   ```
5) Enable and verify:
   ```bash
   sudo systemctl enable --now docker
   docker --version
   docker run --rm hello-world
   ```

Note
- URSim images are Linux-based; on Windows, ensure Docker Desktop is set to Linux containers.
- On Linux, if `docker run hello-world` fails with permissions, log out/in to refresh group membership.

## Quick Start

Windows
1) Open PowerShell in the repo root.
2) Create the Conda environment and install deps:
   ```powershell
   .\Scripts\setup_Windows.ps1
   # After it completes, in a new shell:
   conda activate tablet-robot
   ```
3) (Optional) Start URSim in Docker:
   ```powershell
   .\Scripts\ur_start.ps1
   ```
   PowerShell will print links (noVNC/web) and the RTDE port (default 30004).
4) In the URSim UI, open the program `rtde_control_loop.urp` (it’s auto-copied) and press Play.
5) From the repo root, run a Python example, e.g. the keyboard control loop:
   ```powershell
   python .\RTDE_Scripts\keyboard_control_loop.py
   ```

Linux / macOS
1) Open a terminal in the repo root.
2) Create the Conda env and install deps:
   ```bash
   ./Scripts/setup_LinuxMac.sh
   # After it completes, in the same shell:
   conda activate tablet-robot
   ```
3) (Optional) Start URSim in Docker (Linux/macOS):
   ```bash
   ./Scripts/ursim_start.sh
   ```
   The script prints the web UI URL and RTDE port (30004). On first run it pulls the image.
4) In the URSim UI, open `rtde_control_loop.urp` and press Play.
5) Run a Python example:
   ```bash
   python RTDE_Scripts/keyboard_control_loop.py
   ```

Note: By default, the scripts connect to `host=localhost` and `port=30004`. If your Python is running inside a different container, use `host=host.docker.internal` or the host IP.


## Running URSim in Docker

We provide scripts that pull, run, and populate URSim with the URP file in `RTDE_Urp/`.

- Linux/macOS: `Scripts/ursim_start.sh`
- Windows PowerShell: `Scripts/ur_start.ps1`

What the scripts do
- Pull image `universalrobots/ursim_e-series`.
- Start a container exposing ports:
  - RTDE: 30004
  - VNC: 5900
  - Web noVNC: 6080 (open in a browser: `http://localhost:6080/vnc.html?...`)
- Bind‑mount your `RTDE_Urp/` folder into the container and copy its content into URSim’s Programs directory.

Environment variable
- `HOST_RTDE_DIR` (optional): point to a different host folder of URP files. Defaults to `./RTDE_Urp` in this repo.

After the container is up
- Open the printed noVNC URL in a browser, or use any VNC client on `localhost:5900`.
- In the URSim UI, load `rtde_control_loop.urp` and press Play. Keep it running while using the Python scripts.

Stopping URSim
- The container runs in the foreground of Docker; stop it from Docker Desktop/CLI: `docker rm -f ursim_e_series`.


## Connecting to a real robot

- Network: Ensure your PC can reach the robot’s IP (same subnet or proper routing).
- On the robot teach pendant (PolyScope): allow remote connections and run the URP program (`rtde_control_loop.urp`).
- From Python, set the `--host` or edit the script variable to the robot’s IP:
  ```bash
  python RTDE_Scripts/record.py --host 192.168.0.10 --config RTDE_Configs/record_configuration.xml
  ```
- Safety: Changing poses can cause motion. Verify your cell, speed limits, and safety config before sending commands.


## Running the example scripts

All scripts assume the Conda env is active.

1) Keyboard control loop (interactive)
   - File: `RTDE_Scripts/keyboard_control_loop.py`
   - Purpose: Streams TCP setpoints to URSim/UR. Can run with or without interactive keyboard control.
   - Defaults: `host=localhost`, `port=30004`, config `RTDE_Configs/control_loop_configuration.xml`.
   - Run:
     ```bash
     python RTDE_Scripts/keyboard_control_loop.py
     ```
   - Controls (press while the terminal window is focused):
     - Arrows: X/Y, PageUp/PageDown: Z
     - W/S: Rx, A/D: Ry, Q/E: Rz
     - + / - : increase/decrease step size
     - R: +5 cm Z, F: −5 cm Z, H: hover +10 cm
     - C: sync commanded pose to current TCP, G: go to home pose, B: flip tool Z by 180°
     - ESC: exit

2) Record data
   - File: `RTDE_Scripts/record.py`
   - Records variables configured in `RTDE_Configs/record_configuration.xml` to CSV (or binary).
   - Example:
     ```bash
     python RTDE_Scripts/record.py --host localhost --port 30004 \
       --config RTDE_Configs/record_configuration.xml --frequency 125 --output robot_data.csv
     ```

3) Plot examples
   - Files: `RTDE_Scripts/example_plotting.py`, `RTDE_Scripts/plot.py`
   - Show how to stream and visualize robot data with `matplotlib`.

4) Control example
   - File: `RTDE_Scripts/example_control_loop.py`
   - Minimal example of sending setpoints using the RTDE client.


## Tablet input (Windows/Linux)

We provide a unified API around platform backends in `WacomWrappers/`.

Basic usage
```python
from WacomWrappers.tablet_reader import TabletReader

reader = TabletReader(normalize=True, smooth_alpha=0.12)  # normalized x,y,p in [0,1]
reader.start()
try:
    x, y, p = reader.read_normalized(timeout=2.0)
    print(x, y, p)
finally:
    reader.stop()
```

Backends
- Windows: `wintab_wrapper.py` (uses WinTab via ctypes). Requires Wacom drivers exposing `Wintab32.dll`.
- Linux: `linux_wacom_evdev.py` (uses `evdev`). User must have read permission for `/dev/input/event*`.
- macOS: No tablet backend here; you can still run RTDE scripts without tablet input.

Linux permissions
- Add your user to the `input` group (if present), or add a udev rule for your device to grant read access.
- Our `setup_LinuxMac.sh` script prints a reminder. You can also run:
  ```bash
  sudo usermod -aG input "$USER"
  # then log out/in
  ```

Windows notes
- In Wacom Tablet Properties, you may need to disable "Windows Ink" for this application to use WinTab.


## Configuration files

- `RTDE_Configs/control_loop_configuration.xml`: variables used by the keyboard control loop.
- `RTDE_Configs/record_configuration.xml`: variables to record in `record.py`.
- `RTDE_Urp/rtde_control_loop.urp`: UR program to load and Play in URSim or on the robot.
- Environment override: set `RTDE_CONFIG` to point the control loop to a different config XML.
  ```bash
  export RTDE_CONFIG=$PWD/RTDE_Configs/control_loop_configuration.xml
  ```


## Development notes

- The UR RTDE client is vendored under `RTDE_Python_Client_Library/` and installed in editable mode by the setup scripts:
  ```bash
  pip install -e RTDE_Python_Client_Library
  ```
- Python requirements (see `requirements.txt`): `PyQt6`, `matplotlib`, `evdev` (Linux), `mkl-service`, `setuptools`, `wheel`.
- Python version: scripts default to Python 3.13 in the provided setup scripts; feel free to adjust.


## Troubleshooting & FAQ

RTDE: "Unable to start synchronization" / Python says no RTDE state
- Ensure the URP program (`rtde_control_loop.urp`) is open and Playing in URSim/on the robot.
- Confirm the host/port: `localhost:30004` for local URSim; robot IP for real hardware.

Docker: permission or daemon errors
- On Linux, ensure your user is in the `docker` group or run with `sudo`.
- Verify Docker Desktop/Engine is running.

Tablet on Linux: no events or permission denied
- Check group membership and udev rules. Try `sudo evtest` to discover the device.
- Ensure `python-evdev` is installed (our setup script installs it if missing).

Tablet on Windows: no data
- Verify Wacom drivers are installed and `Wintab32.dll` is available.
- In Wacom Tablet Properties, disable Windows Ink for this app.

Matplotlib/Qt errors on headless servers
- Use a non-interactive backend or run plotting examples locally with a GUI session.

Curses/keyboard input not working
- The control loop falls back to a print-only mode if curses isn't available; you can still see status.

Still stuck?
- Open an issue with your OS version, Python version, and exact command/output.