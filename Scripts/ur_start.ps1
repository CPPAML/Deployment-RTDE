<#
  ursim_start.ps1 — pull, run, and load programs for URSim (Windows PowerShell)

  Usage:
    .\ursim_start.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# --- Config ---
$IMAGE = "universalrobots/ursim_e-series"
$CONTAINER_NAME = "ursim_e_series"

# Host folder containing your programs
$HOST_RTDE_DIR = if ($env:HOST_RTDE_DIR) { $env:HOST_RTDE_DIR } else { Join-Path (Get-Location) "RTDE_Urp" }

# Create the local folder if it doesn't exist to prevent Docker errors
if (-not (Test-Path -LiteralPath $HOST_RTDE_DIR)) {
    Write-Host "Creating local directory: $HOST_RTDE_DIR"
    New-Item -Path $HOST_RTDE_DIR -ItemType Directory | Out-Null
}

# Where to mount that folder inside the container
$MOUNT_POINT = "/rtde_src"

# Ports
$PORT_PRIMARY = 30004
$PORT_VNC     = 5900
$PORT_WEB     = 6080

function Log([string]$msg) {
  $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
  Write-Host "[$ts] $msg" -ForegroundColor Cyan
}

# --- Sanity checks ---
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "Docker not found on PATH. Please install Docker Desktop."
}
try { docker info | Out-Null } catch { throw "Docker daemon not reachable. Is Docker Desktop running?" }

$HOST_RTDE_DIR_ABS = (Resolve-Path -LiteralPath $HOST_RTDE_DIR).Path
Log "Using Host Directory: $HOST_RTDE_DIR_ABS"

# --- Pull image ---
Log "Pulling $IMAGE (this may take awhile if not cached)..."
docker pull $IMAGE | Out-Null

# --- Recycle old container ---
if (docker ps -a --format "{{.Names}}" | Select-String -Pattern "^$CONTAINER_NAME$") {
  Log "Removing existing container $CONTAINER_NAME ..."
  docker rm -f $CONTAINER_NAME | Out-Null
}

# --- Start container ---
Log "Starting container..."
docker run --name $CONTAINER_NAME `
  --rm -dit `
  -p ${PORT_PRIMARY}:30004 `
  -p ${PORT_VNC}:5900 `
  -p ${PORT_WEB}:6080 `
  -v "${HOST_RTDE_DIR_ABS}:${MOUNT_POINT}:ro" `
  $IMAGE | Out-Null

# --- Wait for URSim to Initialize Directory Structure ---
Log "Waiting for URSim file system to initialize..."

$PROGRAMS_DIR = $null
$RETRIES = 0
$MAX_RETRIES = 30 # Wait up to 30 seconds

while ($RETRIES -lt $MAX_RETRIES) {

    $checkParams = @(
        "if [ -d /ursim/programs ]; then echo /ursim/programs; exit 0; fi",
        "if [ -d /ursim/programs.UR5e ]; then echo /ursim/programs.UR5e; exit 0; fi",
        "if [ -d /ursim/programs.UR5 ]; then echo /ursim/programs.UR5; exit 0; fi"
    )
    $cmd = $checkParams -join "; "

    $result = docker exec $CONTAINER_NAME /bin/sh -c "$cmd" 2>$null

    if ($result -and $result.Trim().Length -gt 0) {
        $PROGRAMS_DIR = $result.Trim()
        break
    }

    Start-Sleep -Seconds 1
    Write-Host -NoNewline "."
    $RETRIES++
}
Write-Host ""

if (-not $PROGRAMS_DIR) {
    # Dump logs to see why it failed
    docker logs --tail 20 $CONTAINER_NAME
    throw "Timed out waiting for programs directory to appear inside container."
}

Log "Detected internal Programs directory: $PROGRAMS_DIR"

# --- Copy Files & Fix Permissions ---
Log "Copying files from mount..."

# 1. Copy files
docker exec $CONTAINER_NAME sh -c "cp -r ${MOUNT_POINT}/* ${PROGRAMS_DIR}/"

Log "Fixing file ownership (chown ursim:ursim)..."
docker exec -u root $CONTAINER_NAME sh -c "chown -R ursim:ursim ${PROGRAMS_DIR}"

# --- Confirm copy ---
$COUNT = docker exec $CONTAINER_NAME sh -c "ls -1A '$PROGRAMS_DIR' | wc -l"
Log ("Setup complete. Item(s) in programs folder: {0}" -f $COUNT.Trim())

# --- Helpful endpoints ---
Log "--------------------------------------------------------"
Log ("noVNC:  http://localhost:{0}/vnc.html?autoconnect=true&resize=scale" -f $PORT_WEB)
Log ("VNC:    localhost:{0}" -f $PORT_VNC)
Log ("RTDE:   localhost:{0}" -f $PORT_PRIMARY)
Log "--------------------------------------------------------"