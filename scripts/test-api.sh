#!/usr/bin/env bash
# Smoke-test TTS/STT on a running voice-gpu-server.
#
# Reads config from project .env (VOICE_GPU_API_KEY, VOICE_GPU_BASE_URL, VOICE_GPU_PORT).
#
# Usage:
#   ./scripts/test-api.sh
#   ./scripts/test-api.sh http://127.0.0.1:8765
#   ./scripts/test-api.sh https://your-name.ngrok-free.dev
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VOICES_DIR="${PROJECT_ROOT}/voices"
OUT_DIR="${PROJECT_ROOT}/.test-output"
ENV_FILE="${PROJECT_ROOT}/.env"

# Read a single KEY=value from .env (no bash source — safe for special chars)
env_get() {
  local key="$1"
  [[ -f "${ENV_FILE}" ]] || return 0
  grep -E "^[[:space:]]*${key}=" "${ENV_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' \
    | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
          -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

load_env() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    fail "Missing ${ENV_FILE} — copy .env.example to .env and set VOICE_GPU_API_KEY"
  fi

  # .env is the default; exported shell vars can override if already set
  if [[ -z "${VOICE_GPU_API_KEY:-}" ]]; then
    VOICE_GPU_API_KEY="$(env_get VOICE_GPU_API_KEY)"
  fi
  if [[ -z "${VOICE_GPU_BASE_URL:-}" ]]; then
    VOICE_GPU_BASE_URL="$(env_get VOICE_GPU_BASE_URL)"
  fi
  if [[ -z "${VOICE_GPU_PORT:-}" ]]; then
    VOICE_GPU_PORT="$(env_get VOICE_GPU_PORT)"
  fi
  VOICE_GPU_PORT="${VOICE_GPU_PORT:-8765}"
}

pass() { echo "✅ $*"; }
fail() { echo "❌ $*"; exit 1; }
warn() { echo "⚠️  $*"; }

load_env

API_KEY="${VOICE_GPU_API_KEY:?Set VOICE_GPU_API_KEY in ${ENV_FILE}}"

# Base URL: CLI arg > VOICE_GPU_BASE_URL from .env > localhost
if [[ -n "${1:-}" ]]; then
  BASE_URL="$1"
elif [[ -n "${VOICE_GPU_BASE_URL:-}" ]]; then
  BASE_URL="${VOICE_GPU_BASE_URL}"
else
  BASE_URL="http://127.0.0.1:${VOICE_GPU_PORT}"
fi
BASE_URL="${BASE_URL%/}"

AUTH=(-H "Authorization: Bearer ${API_KEY}")
NGROK_HDR=()
if [[ "$BASE_URL" == *ngrok* ]]; then
  NGROK_HDR=(-H "ngrok-skip-browser-warning: true")
fi

# First TTS/STT requests load GPU models — allow up to 10 minutes
CURL_OPTS=(-sS --connect-timeout 15 --max-time 600)

mkdir -p "$OUT_DIR"

echo "=== voice-gpu-server API tests ==="
echo "Env file: ${ENV_FILE}"
echo "Base URL: ${BASE_URL}"
echo "Output:   ${OUT_DIR}"
echo ""

# --- 1. Health ---
echo "--- 1. Health ---"
HEALTH_BODY=$(curl "${CURL_OPTS[@]}" "${NGROK_HDR[@]}" "${BASE_URL}/health")
echo "$HEALTH_BODY" | python3 -m json.tool
echo "$HEALTH_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok', d" \
  && pass "health ok" || fail "health failed"

# --- 2. List voices ---
echo ""
echo "--- 2. List voices ---"
VOICES_RAW=$(curl "${CURL_OPTS[@]}" "${NGROK_HDR[@]}" "${AUTH[@]}" \
  -w $'\n%{http_code}' "${BASE_URL}/v1/voices")
VOICES_CODE="${VOICES_RAW##*$'\n'}"
VOICES_BODY="${VOICES_RAW%$'\n'*}"
echo "$VOICES_BODY" | python3 -m json.tool
[[ "$VOICES_CODE" == "200" ]] || fail "list voices HTTP ${VOICES_CODE}"
echo "$VOICES_BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ids = {v['voice_id'] for v in d.get('voices', [])}
for name in ('kelvin', 'lim'):
    assert name in ids, f'missing voice: {name}'
print('voices:', sorted(ids))
" && pass "kelvin and lim found" || fail "voices missing"

# --- 3. TTS non-streaming ---
echo ""
echo "--- 3. TTS (kelvin, non-streaming WAV) — first run may load GPU model (slow) ---"
TTS_RAW=$(curl "${CURL_OPTS[@]}" "${NGROK_HDR[@]}" "${AUTH[@]}" \
  -H "Content-Type: application/json" \
  -X POST "${BASE_URL}/v1/tts" \
  -d '{"text":"Hi, Kevin from One CoSec, ah [chuckle].","voice_id":"kelvin","stream":false,"response_format":"wav"}' \
  -w $'\n%{http_code}')
TTS_CODE="${TTS_RAW##*$'\n'}"
TTS_BODY="${TTS_RAW%$'\n'*}"
[[ "$TTS_CODE" == "200" ]] || { echo "$TTS_BODY" | python3 -m json.tool 2>/dev/null || echo "$TTS_BODY"; fail "TTS HTTP ${TTS_CODE}"; }
echo "$TTS_BODY" | python3 -c "
import sys, json, base64, os
d = json.load(sys.stdin)
meta = {k: d[k] for k in d if k != 'audio_base64'}
print(meta)
b64 = d.get('audio_base64') or ''
print('audio_base64 length:', len(b64))
assert b64, 'empty audio_base64'
out = os.path.join('${OUT_DIR}', 'tts-kelvin.wav')
open(out, 'wb').write(base64.b64decode(b64))
print('wrote', out)
"
test -s "${OUT_DIR}/tts-kelvin.wav" && pass "TTS kelvin WAV saved" || fail "TTS output empty"

# --- 4. TTS streaming ---
echo ""
echo "--- 4. TTS (lim, streaming PCM) ---"
TTS_STREAM_CODE=$(curl "${CURL_OPTS[@]}" "${NGROK_HDR[@]}" "${AUTH[@]}" \
  -H "Content-Type: application/json" \
  -X POST "${BASE_URL}/v1/tts" \
  -d '{"text":"Hello from Lim, lah.","voice_id":"lim","stream":true,"response_format":"pcm"}' \
  -D "${OUT_DIR}/tts-lim-headers.txt" \
  -o "${OUT_DIR}/tts-lim.pcm" \
  -w "%{http_code}")
head -20 "${OUT_DIR}/tts-lim-headers.txt"
[[ "$TTS_STREAM_CODE" == "200" ]] || fail "streaming TTS HTTP ${TTS_STREAM_CODE}"
if [[ "$(head -c 1 "${OUT_DIR}/tts-lim.pcm")" == "{" ]]; then
  cat "${OUT_DIR}/tts-lim.pcm"
  fail "streaming TTS returned JSON error instead of PCM"
fi
PCM_BYTES=$(wc -c < "${OUT_DIR}/tts-lim.pcm")
[[ "$PCM_BYTES" -gt 1000 ]] && pass "streaming TTS PCM (${PCM_BYTES} bytes)" || fail "streaming TTS too small (${PCM_BYTES} bytes)"

# --- 5. STT ---
echo ""
echo "--- 5. STT (upload lim.wav) — first run may load GPU model (slow) ---"
[[ -f "${VOICES_DIR}/lim.wav" ]] || fail "missing ${VOICES_DIR}/lim.wav"
STT_RAW=$(curl "${CURL_OPTS[@]}" "${NGROK_HDR[@]}" "${AUTH[@]}" \
  -F "file=@${VOICES_DIR}/lim.wav;type=audio/wav" \
  "${BASE_URL}/v1/stt" \
  -w $'\n%{http_code}')
STT_CODE="${STT_RAW##*$'\n'}"
STT_BODY="${STT_RAW%$'\n'*}"
echo "$STT_BODY" | python3 -m json.tool
[[ "$STT_CODE" == "200" ]] || fail "STT HTTP ${STT_CODE}: $(echo "$STT_BODY" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("detail",""))' 2>/dev/null || echo "$STT_BODY")"
STT_TEXT=$(echo "$STT_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('text','').strip())")
[[ -n "$STT_TEXT" ]] && pass "STT text: ${STT_TEXT:0:120}..." || fail "STT returned empty text"

# --- 6. Auth ---
echo ""
echo "--- 6. Auth rejection (no key) ---"
AUTH_CODE=$(curl "${CURL_OPTS[@]}" "${NGROK_HDR[@]}" -o /dev/null -w "%{http_code}" "${BASE_URL}/v1/voices")
if [[ "$AUTH_CODE" == "401" ]]; then
  pass "unauthenticated request rejected (401)"
else
  warn "expected 401 without API key, got ${AUTH_CODE} (VOICE_GPU_API_KEY may be unset on server)"
fi

echo ""
pass "All API smoke tests passed"
