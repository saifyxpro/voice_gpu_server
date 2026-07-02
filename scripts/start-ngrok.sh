#!/usr/bin/env bash
# Expose the voice-gpu-server via ngrok and print the public URL.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

PORT="${VOICE_GPU_PORT:-8765}"
NGROK_BIN="${NGROK_BIN:-ngrok}"

if ! command -v "${NGROK_BIN}" >/dev/null 2>&1; then
  echo "ngrok not found. Install from https://ngrok.com/download" >&2
  exit 1
fi

if [[ -z "${NGROK_AUTHTOKEN:-}" ]]; then
  echo "Set NGROK_AUTHTOKEN in .env (get one at https://dashboard.ngrok.com/get-started/your-authtoken)" >&2
  exit 1
fi

"${NGROK_BIN}" config add-authtoken "${NGROK_AUTHTOKEN}" >/dev/null 2>&1 || true

echo "Starting ngrok tunnel to localhost:${PORT} ..."
echo "After ngrok starts, copy the https URL into VOICE_GPU_BASE_URL in:"
echo "  - ${PROJECT_ROOT}/.env"
echo "  - pipecat/.env (for my-bot-gpu.py)"
echo ""
echo "Press Ctrl+C to stop."

exec "${NGROK_BIN}" http "${PORT}" --log=stdout
