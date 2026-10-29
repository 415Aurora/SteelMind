#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="${STEELMIND_CONDA_ENV:-steelmind}"

cd "$SCRIPT_DIR"

if ! command -v conda >/dev/null 2>&1; then
  echo "Conda was not found. Install Anaconda/Miniconda and initialize it for this shell." >&2
  exit 1
fi

if ! conda run -n "$ENV_NAME" python --version >/dev/null 2>&1; then
  echo "Creating Conda environment '$ENV_NAME' from environment.yml..."
  conda env create -f "$SCRIPT_DIR/environment.yml" -n "$ENV_NAME"
fi

echo "Installing/updating SteelMind backend dependencies..."
conda run -n "$ENV_NAME" python -m pip install --disable-pip-version-check -r "$SCRIPT_DIR/backend/requirements.txt"

echo "Starting SteelMind gateway at http://127.0.0.1:8000"
echo "Health check: http://127.0.0.1:8000/health"
conda run --no-capture-output -n "$ENV_NAME" python -m uvicorn app:app --app-dir "$SCRIPT_DIR/backend" --host 127.0.0.1 --port 8000
