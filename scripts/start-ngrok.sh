#!/usr/bin/env bash
# Expose voice-gpu-server via ngrok (official agent CLI).
#
# One-time on the server (if not done already):
#   ngrok config add-authtoken YOUR_TOKEN
#
# Find your static free dev domain: Dashboard → Gateway → Domains
# Then set NGROK_URL in .env, e.g. https://your-name.ngrok-free.dev
#
# Usage:
#   ./scripts/start-ngrok.sh
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
NGROK_URL="${NGROK_URL:-${NGROK_DOMAIN:-}}"

if ! command -v "${NGROK_BIN}" >/dev/null 2>&1; then
  echo "ngrok not found. Install: https://ngrok.com/download" >&2
  exit 1
fi

# Optional: write token from .env (run once; stored in ~/.config/ngrok/ngrok.yml)
if [[ -n "${NGROK_AUTHTOKEN:-}" ]]; then
  "${NGROK_BIN}" config add-authtoken "${NGROK_AUTHTOKEN}" >/dev/null 2>&1 || true
fi

# Verify agent is authenticated (per ngrok docs — token in ngrok.yml)
if ! "${NGROK_BIN}" config check >/dev/null 2>&1; then
  cat >&2 <<EOF
ngrok is not authenticated on this machine.

Run once (get token from https://dashboard.ngrok.com/get-started/your-authtoken):

  ngrok config add-authtoken YOUR_TOKEN

Or set NGROK_AUTHTOKEN in ${ENV_FILE}
EOF
  exit 1
fi

# Normalize URL (free static dev domain from your account)
if [[ -n "${NGROK_URL}" && "${NGROK_URL}" != http* ]]; then
  NGROK_URL="https://${NGROK_URL}"
fi

echo "Starting ngrok → localhost:${PORT}"
if [[ -n "${NGROK_URL}" ]]; then
  echo "Using static dev domain: ${NGROK_URL}"
  echo "Set VOICE_GPU_BASE_URL=${NGROK_URL} in ${ENV_FILE} and pipecat/.env"
else
  echo "No NGROK_URL set — ngrok will use your account's assigned dev domain."
  echo "Find it in Dashboard → Gateway → Domains, then add NGROK_URL to .env"
fi
echo ""
echo "Free-plan API clients must send header: ngrok-skip-browser-warning: true"
echo "Local inspector: http://127.0.0.1:4040"
echo "Press Ctrl+C to stop."
echo ""

if [[ -n "${NGROK_URL}" ]]; then
  exec "${NGROK_BIN}" http "${PORT}" --url="${NGROK_URL}" --log=stdout
else
  exec "${NGROK_BIN}" http "${PORT}" --log=stdout
fi
