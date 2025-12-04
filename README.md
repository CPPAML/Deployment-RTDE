# Deployment-RTDE

This repository contains Python scripts and tools for controlling Universal Robots (UR) e-Series manipulators using the Real-Time Data Exchange (RTDE) interface. It provides examples for controlling the robot via a Wacom tablet and keyboard, along with a Docker-based simulation environment.

## Features

- **RTDE Client Library**: Includes a Python client for high-frequency communication with UR robots.
- **Control Loops**:
  - **Wacom Tablet Control**: Maps absolute pen position to the robot's workspace (X and Y axes only).
  - **Keyboard Control**: Interactive keyboard control for the robot end-effector in full SE(3) (X, Y, Z, Rx, Ry, Rz).
- **Simulation Support**: Helper scripts to launch URSim (Universal Robots Simulator) in Docker, pre-configured with necessary programs.
- **Cross-Platform Wrappers**: Includes `WacomWrappers` containing `tablet_reader.py`, which interfaces with Wintab drivers on Windows to read tablet data.

## Prerequisites

- **Python 3.8+**
- **Docker Desktop** (Required for running the URSim simulator on Windows. **Must be running** for the scripts to work).
- **Wacom Drivers** (Required if using `wacom_control_loop.py` on Windows).

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd Deployment-RTDE
    ```

2.  **Install Python dependencies:**
    
    The `requirements.txt` file includes external packages and sets up the local `RTDE_Python_Client_Library` in editable mode (`pip -e`).
    ```bash
    pip install -r requirements.txt
    ```
    
    *Note: If you prefer to install manually, you must ensure `RTDE_Python_Client_Library` is installed via `pip install -e RTDE_Python_Client_Library/`.*

## Usage

### 1. Starting the Simulator (URSim)

To test the control loops without a physical robot, use the provided PowerShell script to launch URSim in Docker.

```powershell
.\Scripts\ur_start.ps1
```

**How it works:**
- This script starts the `universalrobots/ursim_e-series` Docker container.
- **Volume Mounting**: It mounts the local `RTDE_Urp/` directory to the container's program folder. This ensures that all `.urp` files (like `rtde_control_loop.urp` and `rtde_streaming_control_loop.urp`) in `RTDE_Urp` are automatically available inside the simulator.
- Exposes the RTDE interface on port **30004**.
- Provides a VNC interface at [http://localhost:6080/vnc.html](http://localhost:6080/vnc.html).

**Important:** Docker Desktop must be installed and running on Windows for this to work.

### 2. Robot Programs (.urp)

There are two main control strategies provided in the `RTDE_Urp` folder:

1.  **`rtde_control_loop.urp`**: 
    - Uses the `movej` command.
    - Requires a **"handshake"** (synchronization) between the computer and the robot. The Python script must send a specific watchdog or signal to keep the loop running.
    
2.  **`rtde_streaming_control_loop.urp`**: 
    - Uses the `servoj` command.
    - **No handshake** required. It streams joint positions asynchronously, often resulting in smoother continuous motion but requires careful timing handling in the client.

### 3. Running Control Loops

**Important:** Ensure the robot (or simulator) is running and the appropriate `.urp` program is loaded and playing.

**Environment Variables (Optional):**
- `RTDE_HOST`: IP address of the robot (default: `localhost`).
- `RTDE_CONFIG`: Path to configuration XML (default: `RTDE_Configs/control_loop_configuration.xml`).

#### Wacom Tablet Control
Controls the robot using a Wacom tablet.

```bash
python RTDE_Scripts/wacom_control_loop.py
```
- **Scope**: Controls **X and Y** position only (Planar control). Z and rotation are fixed.
- **Tablet Reader**: Uses `WacomWrappers/tablet_reader.py` to read high-frequency data from the tablet.

#### Keyboard Control
Controls the robot using keyboard inputs.

```bash
python RTDE_Scripts/keyboard_control_loop.py
```
- **Scope**: Controls the robot in full **SE(3)** (Translation X, Y, Z and Rotation Rx, Ry, Rz).

### 4. Utilities

- **`RTDE_Scripts/record.py`**: Utility to record RTDE data to a CSV file.
- **`RTDE_Scripts/plot.py`**: Utility to plot recorded data.

## Project Structure

- **RTDE_Scripts/**: Main control scripts (`wacom_control_loop.py`, `keyboard_control_loop.py`).
- **RTDE_Configs/**: XML configuration files defining the RTDE recipes (inputs/outputs).
- **RTDE_Urp/**: URScript/Polyscope programs (`.urp`) to be loaded on the robot. These are mounted into the Docker container.
- **WacomWrappers/**: Python package for interfacing with Wacom tablets. Contains `tablet_reader.py` and `wintab_wrapper.py`.
- **Scripts/**: Helper scripts like `ur_start.ps1` for Docker management.
- **RTDE_Python_Client_Library/**: The core library handling the RTDE protocol.

## Troubleshooting

- **Import Errors**: If `RTDE_Python_Client_Library` is not found, run `pip install -r requirements.txt` (or `pip install -e RTDE_Python_Client_Library/` manually).
- **Connection Failed**: Verify Docker Desktop is running and the container is active (`docker ps`).
- **Tablet Not Found**: Ensure Wacom drivers are installed. The script requires Wintab (standard Wacom driver interface) on Windows.
