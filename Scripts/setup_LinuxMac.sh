#!/usr/bin/env bash
set -euo pipefail

echo "=== Tablet/Robot Dev Environment Setup (Linux/macOS) ==="
read -rp "Conda env name [tablet-robot]: " ENV_NAME
ENV_NAME="${ENV_NAME:-tablet-robot}"
PY_VER="3.13"

# Resolve repo root (folder containing this script, one level up)
SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RTDE_DIR="$REPO_ROOT/RTDE_Python_Client_Library"
REQ_FILE="$REPO_ROOT/requirements.txt"

echo "==> Repo root: $REPO_ROOT"
echo "==> Conda env: $ENV_NAME  (Python $PY_VER)"

# Ensure conda is available and load its shell functions
if ! command -v conda >/dev/null 2>&1; then
  echo "ERROR: 'conda' not found in PATH. Install Miniconda/Anaconda and retry." >&2
  exit 1
fi
CONDA_BASE="$(conda info --base)"
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"

# If RTDE dir is a submodule, init it
if [[ ! -d "$RTDE_DIR" && -f "$REPO_ROOT/.gitmodules" ]]; then
  echo "==> Initializing git submodules..."
  (cd "$REPO_ROOT" && git submodule update --init --recursive)
fi

create_env() {
  echo "==> Creating conda env '$ENV_NAME' (python=$PY_VER) ..."
  conda create -y -n "$ENV_NAME" "python=$PY_VER"
}

# Create env if missing (try default channels, then conda-forge)
if ! conda env list | grep -Eq "^\s*${ENV_NAME}\s"; then
  if ! create_env; then
    echo "==> Retrying with conda-forge channel..."
    conda create -y -n "$ENV_NAME" -c conda-forge "python=$PY_VER"
  fi
else
  echo "==> Conda env '$ENV_NAME' already exists."
fi

echo "==> Activating env..."
conda activate "$ENV_NAME"

echo "==> Upgrading pip..."
python -m pip install --upgrade pip

# Install requirements if present
if [[ -f "$REQ_FILE" ]]; then
  echo "==> Installing from requirements.txt..."
  pip install -r "$REQ_FILE"
else
  echo "WARN: requirements.txt not found at $REQ_FILE (skipping)."
fi

# Ensure evdev on Linux for tablet backend
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
  python - <<'PY' >/dev/null 2>&1 || { echo "==> Installing python-evdev..."; pip install evdev; }
import importlib; importlib.import_module("evdev")
PY
fi

# Install RTDE client in editable mode
if [[ -d "$RTDE_DIR" ]]; then
  echo "==> pip install -e $RTDE_DIR"
  pip install -e "$RTDE_DIR"
else
  echo "WARN: RTDE_Python_Client_Library not found at $RTDE_DIR; skipping editable install."
fi

echo
echo "🎉 Done!"
echo "To use the env now:  conda activate $ENV_NAME"
echo "Linux Wacom note: ensure your user can read /dev/input/* (e.g., add to 'input' group or add a udev rule)."
