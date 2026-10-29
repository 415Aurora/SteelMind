#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${STEELMIND_VENV:-${SCRIPT_DIR}/.venv}"
PYTHON="${VENV_DIR}/bin/python"

cd "$SCRIPT_DIR"

if [[ ! -x "$PYTHON" ]]; then
  if [[ -n "${STEELMIND_PYTHON:-}" ]]; then
    BASE_PYTHON="$STEELMIND_PYTHON"
  elif command -v python3.12 >/dev/null 2>&1; then
    BASE_PYTHON="$(command -v python3.12)"
  elif command -v python3 >/dev/null 2>&1; then
    BASE_PYTHON="$(command -v python3)"
  else
    echo "Python 3 was not found. Install Python 3.12 (recommended) and retry." >&2
    exit 1
  fi

  echo "Creating virtual environment: $VENV_DIR"
  "$BASE_PYTHON" -m venv "$VENV_DIR"
  PYTHON="${VENV_DIR}/bin/python"
  echo "Installing SteelMind backend dependencies..."
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install -r "$SCRIPT_DIR/backend/requirements.txt"
fi

echo "Starting SteelMind tool gateway at http://127.0.0.1:8000"
echo "Health check: http://127.0.0.1:8000/health"
exec "$PYTHON" -m uvicorn app:app --app-dir "$SCRIPT_DIR/backend" --host 127.0.0.1 --port 8000
