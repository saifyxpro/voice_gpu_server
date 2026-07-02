#!/usr/bin/env bash
# Start voice-gpu-server using Lightning's conda env (cloudspace).
# Do NOT use 'uv run' — it creates a separate .venv on Lightning Studios.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

if [[ -z "${CONDA_DEFAULT_ENV:-}" ]]; then
  echo "Activate Lightning conda env first: conda activate cloudspace" >&2
  exit 1
fi

exec python -m voice_gpu_server
