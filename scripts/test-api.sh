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

# Read a single KEY=value from .env (supports export PREFIX, quotes, inline comments)
env_get() {
  local key="$1"
  [[ -f "${ENV_FILE}" ]] || return 0
  python3 - "${key}" "${ENV_FILE}" <<'PY'
import sys
from pathlib import Path

key, path = sys.argv[1], Path(sys.argv[2])
value = ""
for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[7:].strip()
    if "=" not in line:
        continue
    name, _, val = line.partition("=")
    if name.strip() != key:
        continue
    val = val.strip()
    if " #" in val:
        val = val.split(" #", 1)[0].rstrip()
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        val = val[1:-1]
    value = val
print(value, end="")
PY
}

load_env() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    fail "Missing ${ENV_FILE} — copy .env.example to .env and set VOICE_GPU_API_KEY"
  fi

  # .env is authoritative (ignore stale shell exports like VOICE_GPU_API_KEY=your-key)
  local from_env
  from_env="$(env_get VOICE_GPU_API_KEY)"
  [[ -n "${from_env}" ]] && VOICE_GPU_API_KEY="${from_env}"

  from_env="$(env_get VOICE_GPU_BASE_URL)"
  [[ -n "${from_env}" ]] && VOICE_GPU_BASE_URL="${from_env}"

  from_env="$(env_get VOICE_GPU_PORT)"
  [[ -n "${from_env}" ]] && VOICE_GPU_PORT="${from_env}"

  VOICE_GPU_PORT="${VOICE_GPU_PORT:-8765}"

  if [[ -z "${VOICE_GPU_API_KEY:-}" ]]; then
    fail "VOICE_GPU_API_KEY is empty in ${ENV_FILE}"
  fi
  if [[ "${VOICE_GPU_API_KEY}" == "change-me-to-a-long-random-string" || "${VOICE_GPU_API_KEY}" == "your-key" ]]; then
    fail "VOICE_GPU_API_KEY in ${ENV_FILE} is still a placeholder — set your real key"
  fi
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
echo "API key:  loaded (${#API_KEY} chars)"
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
[[ "$VOICES_CODE" == "200" ]] || {
  if [[ "$VOICES_CODE" == "401" ]]; then
    fail "list voices HTTP 401 — VOICE_GPU_API_KEY in .env does not match the running server (loaded ${#API_KEY} chars). Restart server after editing .env."
  fi
  fail "list voices HTTP ${VOICES_CODE}"
}
echo "$VOICES_BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ids = {v['voice_id'] for v in d.get('voices', [])}
for name in ('kelvin', 'lim'):
    assert name in ids, f'missing voice: {name}'
print('voices:', sorted(ids))
" && pass "kelvin and lim found" || fail "voices missing"

# Build JSON TTS payload safely (handles quotes, tags, apostrophes)
tts_payload() {
  local voice_id="$1"
  local stream="$2"
  local format="$3"
  local text="$4"
  local out_file="$5"
  python3 - "$voice_id" "$stream" "$format" "$text" "$out_file" <<'PY'
import json, sys
voice_id, stream, fmt, text, out = sys.argv[1:6]
with open(out, "w", encoding="utf-8") as f:
    json.dump(
        {
            "text": text,
            "voice_id": voice_id,
            "stream": stream.lower() == "true",
            "response_format": fmt,
        },
        f,
        ensure_ascii=False,
    )
PY
}

# --- 3. TTS kelvin (non-streaming WAV + expressive tags) ---
echo ""
echo "--- 3. TTS (kelvin, non-streaming WAV + expressive tags) ---"
KELVIN_TEXT="Hi, good afternoon. [clear throat] This is Kevin from One CoSec, ah [chuckle]. Got a few reminders about your AGM and filing dates lor. [sigh] Don't worry lah, quite straightforward one. You free now to talk, or you prefer I send everything by email instead hor?"
echo "text: ${KELVIN_TEXT}"
tts_payload kelvin false wav "$KELVIN_TEXT" "${OUT_DIR}/payload-kelvin.json"
TTS_RAW=$(curl "${CURL_OPTS[@]}" "${NGROK_HDR[@]}" "${AUTH[@]}" \
  -H "Content-Type: application/json" \
  -X POST "${BASE_URL}/v1/tts" \
  -d @"${OUT_DIR}/payload-kelvin.json" \
  -w $'\n%{http_code}')
TTS_CODE="${TTS_RAW##*$'\n'}"
TTS_BODY="${TTS_RAW%$'\n'*}"
[[ "$TTS_CODE" == "200" ]] || { echo "$TTS_BODY" | python3 -m json.tool 2>/dev/null || echo "$TTS_BODY"; fail "TTS kelvin HTTP ${TTS_CODE}"; }
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
test -s "${OUT_DIR}/tts-kelvin.wav" && pass "TTS kelvin WAV saved" || fail "TTS kelvin output empty"

# --- 4. TTS lim (non-streaming WAV + expressive tags) ---
echo ""
echo "--- 4. TTS (lim, non-streaming WAV + expressive tags) ---"
LIM_TEXT="Hello, Lim here from One CoSec again, ah. [clear throat] Just a gentle reminder leh — your annual return deadline coming up already, so I thought I'll give you a quick call. Nothing to panic about lah [chuckle]. If you already submitted, can let me know hor? Otherwise I can walk you through the steps now — you got five minutes or not?"
echo "text: ${LIM_TEXT}"
tts_payload lim false wav "$LIM_TEXT" "${OUT_DIR}/payload-lim.json"
TTS_LIM_RAW=$(curl "${CURL_OPTS[@]}" "${NGROK_HDR[@]}" "${AUTH[@]}" \
  -H "Content-Type: application/json" \
  -X POST "${BASE_URL}/v1/tts" \
  -d @"${OUT_DIR}/payload-lim.json" \
  -w $'\n%{http_code}')
TTS_LIM_CODE="${TTS_LIM_RAW##*$'\n'}"
TTS_LIM_BODY="${TTS_LIM_RAW%$'\n'*}"
[[ "$TTS_LIM_CODE" == "200" ]] || { echo "$TTS_LIM_BODY" | python3 -m json.tool 2>/dev/null || echo "$TTS_LIM_BODY"; fail "TTS lim HTTP ${TTS_LIM_CODE}"; }
echo "$TTS_LIM_BODY" | python3 -c "
import sys, json, base64, os
d = json.load(sys.stdin)
meta = {k: d[k] for k in d if k != 'audio_base64'}
print(meta)
b64 = d.get('audio_base64') or ''
print('audio_base64 length:', len(b64))
assert b64, 'empty audio_base64'
out = os.path.join('${OUT_DIR}', 'tts-lim.wav')
open(out, 'wb').write(base64.b64decode(b64))
print('wrote', out)
"
test -s "${OUT_DIR}/tts-lim.wav" && pass "TTS lim WAV saved" || fail "TTS lim output empty"

# --- 5. TTS streaming (kelvin + lim) ---
echo ""
echo "--- 5. TTS streaming PCM (kelvin + lim) ---"
for VOICE in kelvin lim; do
  STREAM_TEXT="Hey there [chuckle], quick test from ${VOICE}, ah. Can hear me okay or not?"
  echo "streaming ${VOICE}: ${STREAM_TEXT}"
  tts_payload "$VOICE" true pcm "$STREAM_TEXT" "${OUT_DIR}/payload-${VOICE}-stream.json"
  TTS_STREAM_CODE=$(curl "${CURL_OPTS[@]}" "${NGROK_HDR[@]}" "${AUTH[@]}" \
    -H "Content-Type: application/json" \
    -X POST "${BASE_URL}/v1/tts" \
    -d @"${OUT_DIR}/payload-${VOICE}-stream.json" \
    -D "${OUT_DIR}/tts-${VOICE}-stream-headers.txt" \
    -o "${OUT_DIR}/tts-${VOICE}-stream.pcm" \
    -w "%{http_code}")
  head -8 "${OUT_DIR}/tts-${VOICE}-stream-headers.txt"
  [[ "$TTS_STREAM_CODE" == "200" ]] || fail "streaming TTS ${VOICE} HTTP ${TTS_STREAM_CODE}"
  if python3 -c "import sys; sys.exit(0 if open('${OUT_DIR}/tts-${VOICE}-stream.pcm','rb').read(1) != b'{' else 1)"; then
    PCM_BYTES=$(wc -c < "${OUT_DIR}/tts-${VOICE}-stream.pcm")
    [[ "$PCM_BYTES" -gt 1000 ]] && pass "streaming TTS ${VOICE} PCM (${PCM_BYTES} bytes)" || fail "streaming TTS ${VOICE} too small (${PCM_BYTES} bytes)"
  else
    cat "${OUT_DIR}/tts-${VOICE}-stream.pcm"
    fail "streaming TTS ${VOICE} returned JSON error instead of PCM"
  fi
done

# --- 6. STT (both reference voices) ---
stt_upload() {
  local label="$1"
  local wav_path="$2"
  echo ""
  echo "--- STT (${label}: $(basename "$wav_path")) ---"
  [[ -f "$wav_path" ]] || fail "missing ${wav_path}"
  STT_RAW=$(curl "${CURL_OPTS[@]}" "${NGROK_HDR[@]}" "${AUTH[@]}" \
    -F "file=@${wav_path};type=audio/wav" \
    "${BASE_URL}/v1/stt" \
    -w $'\n%{http_code}')
  STT_CODE="${STT_RAW##*$'\n'}"
  STT_BODY="${STT_RAW%$'\n'*}"
  echo "$STT_BODY" | python3 -m json.tool
  [[ "$STT_CODE" == "200" ]] || fail "STT ${label} HTTP ${STT_CODE}: $(echo "$STT_BODY" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("detail",""))' 2>/dev/null || echo "$STT_BODY")"
  STT_TEXT=$(echo "$STT_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('text','').strip())")
  [[ -n "$STT_TEXT" ]] && pass "STT ${label}: ${STT_TEXT:0:120}..." || fail "STT ${label} returned empty text"
}

echo ""
echo "--- 6. STT (upload reference WAVs) ---"
stt_upload kelvin "${VOICES_DIR}/kelvin.wav"
stt_upload lim "${VOICES_DIR}/lim.wav"

# --- 7. Auth ---
echo ""
echo "--- 7. Auth rejection (no key) ---"
AUTH_CODE=$(curl "${CURL_OPTS[@]}" "${NGROK_HDR[@]}" -o /dev/null -w "%{http_code}" "${BASE_URL}/v1/voices")
if [[ "$AUTH_CODE" == "401" ]]; then
  pass "unauthenticated request rejected (401)"
else
  warn "expected 401 without API key, got ${AUTH_CODE} (VOICE_GPU_API_KEY may be unset on server)"
fi

echo ""
pass "All API smoke tests passed"
