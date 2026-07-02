#!/usr/bin/env bash
# Start voice-gpu-server in the active conda/venv (same env as setup-h100.sh).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."
if [[ -z "${CONDA_DEFAULT_ENV:-}" && -z "${VIRTUAL_ENV:-}" ]]; then
  echo "Activate conda env first: conda activate cloudspace" >&2
  exit 1
fi
exec uv run --active voice-gpu-server
