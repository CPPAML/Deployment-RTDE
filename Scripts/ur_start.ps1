<#
  ursim_start.ps1 — pull, run, and load programs for URSim (Windows PowerShell)

  Usage:
    # from your repo root
    .\ursim_start.ps1

  Notes:
    - Uses $env:HOST_RTDE_DIR if set; otherwise defaults to ".\RTDE_Urp"
    - Requires Docker Desktop with Linux containers
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# --- Config ---
$IMAGE = "universalrobots/ursim_e-series"
$CONTAINER_NAME = "ursim_e_series"

# Host folder containing your programs (change or set $env:HOST_RTDE_DIR)
$HOST_RTDE_DIR = if ($env:HOST_RTDE_DIR) { $env:HOST_RTDE_DIR } else { Join-Path (Get-Location) "RTDE_Urp" }

# Where to mount that folder inside the container
$MOUNT_POINT = "/rtde_src"

# Ports
$PORT_PRIMARY = 30004
$PORT_VNC     = 5900
$PORT_WEB     = 6080

function Log([string]$msg) {
  $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
  Write-Host "[$ts] $msg"
}

# --- Sanity checks ---
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "Docker not found on PATH. Install Docker Desktop and ensure Linux containers are enabled."
}
try { docker info | Out-Null } catch { throw "Docker daemon not reachable. Is Docker Desktop running?" }
if (-not (Test-Path -LiteralPath $HOST_RTDE_DIR)) {
  throw "Host folder not found: $HOST_RTDE_DIR"
}

# Normalize host path for docker (absolute path recommended)
$HOST_RTDE_DIR_ABS = (Resolve-Path -LiteralPath $HOST_RTDE_DIR).Path

# --- Pull image ---
Log "Pulling $IMAGE ..."
docker pull $IMAGE | Out-Null

# --- Recycle any old container ---
$existing = docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq $CONTAINER_NAME }
if ($existing) {
  Log "Removing existing container $CONTAINER_NAME ..."
  docker rm -f $CONTAINER_NAME | Out-Null
}

# --- Start container with bind mount (read-only) ---
Log "Starting container and mounting: $HOST_RTDE_DIR_ABS -> $MOUNT_POINT"
# Note: Docker for Windows accepts Windows absolute paths on -v with Linux containers.
docker run --name $CONTAINER_NAME `
  --rm -dit `
  -p ${PORT_PRIMARY}:30004 `
  -p ${PORT_VNC}:5900 `
  -p ${PORT_WEB}:6080 `
  -v "${HOST_RTDE_DIR_ABS}:${MOUNT_POINT}:ro" `
  $IMAGE | Out-Null

# --- Resolve the active Programs directory inside the container ---
$script = @'
set -e
for d in /ursim/programs.UR5 /ursim/programs.UR5e; do
  [ -d "$d" ] && { echo "$d"; exit 0; }
done
if [ -e /ursim/programs ]; then
  t=$(readlink -f /ursim/programs || true)
  [ -n "$t" ] && [ -d "$t" ] && { echo "$t"; exit 0; }
fi
echo /ursim/programs
'@ -replace "`r",""   # important on Windows

# Use /bin/sh -c (no -l)
$PROGRAMS_DIR = docker exec $CONTAINER_NAME /bin/sh -c "$script" 2>$null
$PROGRAMS_DIR = $PROGRAMS_DIR.Trim()

if (-not $PROGRAMS_DIR) {
  throw "Could not resolve Programs directory inside the container. Try: docker logs $CONTAINER_NAME"
}

# --- Copy RTDE_Urp files into Programs ---
Log "Creating $PROGRAMS_DIR (if missing) and copying files ..."
docker exec $CONTAINER_NAME sh -lc "mkdir -p '$PROGRAMS_DIR'"
docker exec $CONTAINER_NAME sh -lc "cp -r '${MOUNT_POINT}/.' '${PROGRAMS_DIR}/'"

# --- Confirm copy ---
$COUNT = docker exec $CONTAINER_NAME sh -lc "ls -1A '$PROGRAMS_DIR' | wc -l || true"
$COUNT = $COUNT.Trim()
Log ("Copy complete. Item(s) now in {0}: {1}" -f $PROGRAMS_DIR, $COUNT)

# --- Helpful endpoints ---
Log ("noVNC:  http://localhost:{0}/vnc.html?autoconnect=1&resize=scale&host=localhost&port={0}" -f $PORT_WEB)
Log ("VNC:    localhost:{0}" -f $PORT_VNC)
Log ("RTDE:   localhost:{0}" -f $PORT_PRIMARY)
