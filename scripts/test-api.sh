#!/usr/bin/env bash
# Smoke-test TTS/STT on a running voice-gpu-server.
#
# Usage:
#   ./scripts/test-api.sh
#   ./scripts/test-api.sh http://127.0.0.1:8765
#   ./scripts/test-api.sh https://your-name.ngrok-free.dev
#
# Loads VOICE_GPU_API_KEY from .env if not already exported.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VOICES_DIR="${PROJECT_ROOT}/voices"
OUT_DIR="${PROJECT_ROOT}/.test-output"
ENV_FILE="${PROJECT_ROOT}/.env"

BASE_URL="${1:-http://127.0.0.1:8765}"
BASE_URL="${BASE_URL%/}"

# Load API key from .env when not exported
if [[ -z "${VOICE_GPU_API_KEY:-}" && -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "${ENV_FILE}"
  set +a
fi
API_KEY="${VOICE_GPU_API_KEY:?Set VOICE_GPU_API_KEY in env or ${ENV_FILE}}"

AUTH=(-H "Authorization: Bearer ${API_KEY}")
NGROK_HDR=()
if [[ "$BASE_URL" == *ngrok* ]]; then
  NGROK_HDR=(-H "ngrok-skip-browser-warning: true")
fi

# First TTS/STT requests load GPU models — allow up to 10 minutes
CURL_OPTS=(-sS --connect-timeout 15 --max-time 600)

mkdir -p "$OUT_DIR"

pass() { echo "✅ $*"; }
fail() { echo "❌ $*"; exit 1; }
warn() { echo "⚠️  $*"; }

echo "=== voice-gpu-server API tests ==="
echo "Base URL: $BASE_URL"
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
TTS_STREAM_HEADERS=$(curl "${CURL_OPTS[@]}" "${NGROK_HDR[@]}" "${AUTH[@]}" \
  -H "Content-Type: application/json" \
  -X POST "${BASE_URL}/v1/tts" \
  -d '{"text":"Hello from Lim, lah.","voice_id":"lim","stream":true,"response_format":"pcm"}' \
  -D "${OUT_DIR}/tts-lim-headers.txt" \
  -o "${OUT_DIR}/tts-lim.pcm" \
  -w "%{http_code}")
head -20 "${OUT_DIR}/tts-lim-headers.txt"
[[ "$TTS_STREAM_HEADERS" == "200" ]] || fail "streaming TTS HTTP ${TTS_STREAM_HEADERS}"
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
