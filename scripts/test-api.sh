#!/usr/bin/env bash
# Smoke-test TTS/STT on a running voice-gpu-server.
# Usage (on H100 / wherever the server runs):
#   export VOICE_GPU_API_KEY=your-key
#   ./scripts/test-api.sh
#   ./scripts/test-api.sh http://127.0.0.1:8765
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8765}"
BASE_URL="${BASE_URL%/}"
API_KEY="${VOICE_GPU_API_KEY:?Set VOICE_GPU_API_KEY}"
AUTH="Authorization: Bearer ${API_KEY}"
NGROK_HDR=()
if [[ "$BASE_URL" == *ngrok* ]]; then
  NGROK_HDR=(-H "ngrok-skip-browser-warning: true")
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VOICES_DIR="${SCRIPT_DIR}/../voices"
OUT_DIR="${SCRIPT_DIR}/../.test-output"
mkdir -p "$OUT_DIR"

pass() { echo "✅ $*"; }
fail() { echo "❌ $*"; exit 1; }

echo "=== voice-gpu-server API tests ==="
echo "Base URL: $BASE_URL"
echo ""

echo "--- 1. Health ---"
HEALTH=$(curl -sS "${NGROK_HDR[@]}" "$BASE_URL/health")
echo "$HEALTH" | python3 -m json.tool
echo "$HEALTH" | grep -q '"status":"ok"' && pass "health ok" || fail "health failed"

echo ""
echo "--- 2. List voices ---"
VOICES=$(curl -sS "${NGROK_HDR[@]}" -H "$AUTH" "$BASE_URL/v1/voices")
echo "$VOICES" | python3 -m json.tool
echo "$VOICES" | grep -q '"kelvin"' && pass "kelvin voice found" || fail "kelvin missing"
echo "$VOICES" | grep -q '"lim"' && pass "lim voice found" || fail "lim missing"

echo ""
echo "--- 3. TTS (kelvin, non-streaming WAV) ---"
TTS_JSON=$(curl -sS "${NGROK_HDR[@]}" -H "$AUTH" -H "Content-Type: application/json" \
  -X POST "$BASE_URL/v1/tts" \
  -d '{"text":"Hi, Kevin from One CoSec, ah [chuckle].","voice_id":"kelvin","stream":false,"response_format":"wav"}')
echo "$TTS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print({k:d[k] for k in d if k!='audio_base64'}); print('audio_base64 length:', len(d.get('audio_base64','')))"
echo "$TTS_JSON" | python3 -c "import sys,json,base64; d=json.load(sys.stdin); open('${OUT_DIR}/tts-kelvin.wav','wb').write(base64.b64decode(d['audio_base64']))"
test -s "${OUT_DIR}/tts-kelvin.wav" && pass "TTS wrote ${OUT_DIR}/tts-kelvin.wav" || fail "TTS empty"

echo ""
echo "--- 4. TTS (lim, streaming PCM headers) ---"
TTS_HEADERS=$(curl -sS -D - -o "${OUT_DIR}/tts-lim.pcm" "${NGROK_HDR[@]}" -H "$AUTH" \
  -H "Content-Type: application/json" -X POST "$BASE_URL/v1/tts" \
  -d '{"text":"Hello from Lim, lah.","voice_id":"lim","stream":true,"response_format":"pcm"}' | head -20)
echo "$TTS_HEADERS"
test -s "${OUT_DIR}/tts-lim.pcm" && pass "streaming TTS wrote ${OUT_DIR}/tts-lim.pcm ($(wc -c < "${OUT_DIR}/tts-lim.pcm") bytes)" || fail "streaming TTS empty"

echo ""
echo "--- 5. STT (upload lim.wav) ---"
STT=$(curl -sS "${NGROK_HDR[@]}" -H "$AUTH" -F "file=@${VOICES_DIR}/lim.wav" "$BASE_URL/v1/stt")
echo "$STT" | python3 -m json.tool
TEXT=$(echo "$STT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('text','').strip())")
if [[ -n "$TEXT" ]]; then
  pass "STT returned text: ${TEXT:0:120}..."
else
  fail "STT returned empty text"
fi

echo ""
echo "--- 6. Auth rejection (no key) ---"
CODE=$(curl -sS -o /dev/null -w "%{http_code}" "${NGROK_HDR[@]}" "$BASE_URL/v1/voices")
[[ "$CODE" == "401" ]] && pass "unauthenticated request rejected (401)" || echo "⚠️  expected 401, got $CODE (API key may be unset on server)"

echo ""
pass "All API smoke tests passed"
