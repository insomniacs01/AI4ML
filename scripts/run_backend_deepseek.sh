#!/bin/zsh

set -euo pipefail

ROOT_DIR="/Users/focalors/BUAA/SoftwareE/AI4ML"
VENV_DIR="$ROOT_DIR/.venv2"
ENV_FILE="$ROOT_DIR/local/deepseek.env"

cd "$ROOT_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE" >&2
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Missing virtualenv: $VENV_DIR" >&2
  exit 1
fi

source "$VENV_DIR/bin/activate"
source "$ENV_FILE"

exec python -m uvicorn backend.app.main:app --port 8000
