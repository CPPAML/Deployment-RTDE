#!/usr/bin/env bash
# ursim_start.sh — pull, run, and load programs for URSim

set -Eeuo pipefail

IMAGE="universalrobots/ursim_e-series"
CONTAINER_NAME="ursim_e_series"

# --- Host folder containing your programs (change if needed) ---
HOST_RTDE_DIR="${HOST_RTDE_DIR:-$(pwd)/RTDE_Urp}"

# --- Where to mount that folder inside the container temporarily ---
MOUNT_POINT="/rtde_src"

# --- Ports ---
PORT_PRIMARY=30004
PORT_VNC=5900
PORT_WEB=6080

log(){ printf "[%s] %s\n" "$(date +'%Y-%m-%d %H:%M:%S')" "$*"; }

# Sanity checks
command -v docker >/dev/null || { echo "Docker not found"; exit 1; }
docker info >/dev/null || { echo "Docker daemon not reachable"; exit 1; }
[[ -d "$HOST_RTDE_DIR" ]] || { echo "Host folder not found: $HOST_RTDE_DIR"; exit 1; }

# Pull image
log "Pulling ${IMAGE} ..."
docker pull "$IMAGE" >/dev/null

# Recycle any old container
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  log "Removing existing container ${CONTAINER_NAME} ..."
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

# Start container with bind mount
# Tip for SELinux hosts: change ':ro' to ':ro,Z'
log "Starting container and mounting: $HOST_RTDE_DIR -> ${MOUNT_POINT}"
docker run --name "$CONTAINER_NAME" \
  --rm -dit \
  -p ${PORT_PRIMARY}:30004 \
  -p ${PORT_VNC}:5900 \
  -p ${PORT_WEB}:6080 \
  -v "${HOST_RTDE_DIR}:${MOUNT_POINT}:ro" \
  "$IMAGE" >/dev/null

# Resolve the active Programs directory
PROGRAMS_DIR="$(docker exec "$CONTAINER_NAME" sh -lc '
set -e
# Prefer explicit UR5 dirs
for d in /ursim/programs.UR5 /ursim/programs.UR5e; do
  [ -d "$d" ] && { echo "$d"; exit 0; }
done
# Otherwise follow /ursim/programs if present
if [ -e /ursim/programs ]; then
  t=$(readlink -f /ursim/programs || true)
  [ -n "$t" ] && [ -d "$t" ] && { echo "$t"; exit 0; }
fi
# Fallback
echo /ursim/programs
')"

log "Resolved Programs directory: ${PROGRAMS_DIR}"

# Copy RTDE_Urp files into Programs
log "Creating ${PROGRAMS_DIR} (if missing) and copying files ..."
docker exec "$CONTAINER_NAME" sh -lc "mkdir -p '${PROGRAMS_DIR}'"
docker exec "$CONTAINER_NAME" sh -lc "cp -r '${MOUNT_POINT}/.' '${PROGRAMS_DIR}/'"

# Confirm Copy
COUNT="$(docker exec "$CONTAINER_NAME" sh -lc "ls -1A '${PROGRAMS_DIR}' | wc -l || true")"
log "Copy complete. Item(s) now in ${PROGRAMS_DIR}"

# Helpful endpoints
log "noVNC:  http://localhost:${PORT_WEB}/vnc.html?autoconnect=1&resize=scale&host=localhost&port=${PORT_WEB}"
log "VNC:    localhost:${PORT_VNC}"
log "RTDE:   localhost:${PORT_PRIMARY}"
