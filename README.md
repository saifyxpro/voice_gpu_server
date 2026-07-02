# Voice GPU Server

GPU-hosted TTS and STT APIs for voice bots. Runs on an NVIDIA H100 (or any CUDA GPU). LLM is configured separately in your Pipecat client — not part of this server.

| Component | Model | Where it runs |
|-----------|-------|---------------|
| **TTS** | [ResembleAI/chatterbox-turbo](https://huggingface.co/ResembleAI/chatterbox-turbo) | GPU |
| **STT** | [nvidia/canary-qwen-2.5b](https://huggingface.co/nvidia/canary-qwen-2.5b) | GPU |

## Prerequisites (H100 server)

- Linux with NVIDIA driver + CUDA 12.x
- **Python 3.12** (recommended) or 3.11–3.13 — **not 3.14** (PyTorch has no wheels yet)
- [uv](https://docs.astral.sh/uv/)
- ~16 GB+ VRAM recommended (both models loaded; TTS alone is lighter)
- Hugging Face access for model downloads

### Lightning AI Studio (recommended)

Per [Lightning AI Studio docs](https://lightning.ai/docs/platform/build/ai-studio):

- Studios **persist** pip/conda packages automatically under `/teamspace/studios/this_studio`
- Each Studio has **one conda env** (`cloudspace`) — install like a laptop: `pip install` in terminal
- Install on **free CPU** first, switch to **GPU** when ready to run (saves credits)
- **Do not** use `uv run` or `uv sync` — they create a separate `.venv` and break torch/chatterbox/nemo

```bash
cd voice_gpu_server
cp .env.example .env
conda activate cloudspace

chmod +x scripts/setup-lightning.sh scripts/run-server.sh scripts/start-ngrok.sh
./scripts/setup-lightning.sh     # once — persists across Studio restarts

# Terminal 1 — API
./scripts/run-server.sh        # uses: python -m voice_gpu_server

# Terminal 2 — ngrok (set NGROK_URL in .env first)
./scripts/start-ngrok.sh
```

### Other H100 / bare-metal GPU

**Do not mix** `uv sync` (creates `.venv`) with `uv pip install` into conda.

```bash
conda activate your-gpu-env
./scripts/setup-h100.sh
python -m voice_gpu_server
```

**Alternative — uv-managed `.venv` only (no conda):**

```bash
rm -rf .venv
uv python install 3.12
uv sync --python 3.12
uv pip install --python .venv/bin/python torch torchaudio --index-url https://download.pytorch.org/whl/cu124
uv pip install --python .venv/bin/python chatterbox-tts
uv pip install --python .venv/bin/python "nemo_toolkit[asr] @ git+https://github.com/NVIDIA/NeMo.git"
uv run voice-gpu-server
```

Server listens on `http://0.0.0.0:8765` by default.

### Add a voice reference

Chatterbox Turbo needs a ~10s reference clip:

```bash
cp /path/to/speaker.wav voices/kelvin.wav
```

See [voices/README.md](voices/README.md) for the full Chatterbox Turbo tag list (`[clear throat]`, `[sigh]`, `[chuckle]`, `[laugh]`, and six more).

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health + model load status |
| `GET` | `/v1/voices` | List voice reference files |
| `POST` | `/v1/tts` | Text → audio (streaming PCM or JSON) |
| `POST` | `/v1/stt` | WAV upload → transcript |

Auth: set `VOICE_GPU_API_KEY` and pass `Authorization: Bearer <key>` or `X-API-Key: <key>`.

### Examples

**Health check**

```bash
curl http://localhost:8765/health
```

**TTS (non-streaming WAV, base64 in JSON)**

```bash
curl -X POST http://localhost:8765/v1/tts \
  -H "Authorization: Bearer $VOICE_GPU_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hi, this is One CoSec calling [chuckle].",
    "voice_id": "kelvin",
    "stream": false,
    "response_format": "wav"
  }'
```

**TTS (streaming PCM — used by Pipecat)**

```bash
curl -N -X POST http://localhost:8765/v1/tts \
  -H "Authorization: Bearer $VOICE_GPU_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello world","stream":true,"response_format":"pcm"}' \
  --output out.pcm
# Response headers: X-Sample-Rate, X-Voice-Id, X-Audio-Format
```

**STT**

```bash
curl -X POST http://localhost:8765/v1/stt \
  -H "Authorization: Bearer $VOICE_GPU_API_KEY" \
  -F "file=@sample.wav"
```

## Expose via ngrok

Docs: [ngrok Agent CLI](https://ngrok.com/docs/agent/cli/) · [HTTP endpoints](https://ngrok.com/docs/gateway/http/)

Free accounts get a **static dev domain** (e.g. `your-name.ngrok-free.dev`) that does not change on restart. Find yours in **Dashboard → Gateway → Domains**.

### One-time setup (on H100)

```bash
# Authenticate agent (stored in ~/.config/ngrok/ngrok.yml)
ngrok config add-authtoken YOUR_TOKEN

# In .env — your assigned dev domain + public base URL for clients
NGROK_URL=https://your-name.ngrok-free.dev
VOICE_GPU_BASE_URL=https://your-name.ngrok-free.dev
```

### Start tunnel

```bash
chmod +x scripts/start-ngrok.sh
./scripts/start-ngrok.sh
```

The script uses `ngrok http 8765 --url=$NGROK_URL` when `NGROK_URL` is set (recommended). Inspector UI: `http://127.0.0.1:4040`.

**Alternative** — named endpoint via config file:

```bash
cp ngrok.yml.example ~/.config/ngrok/ngrok.yml   # edit YOUR_DEV_DOMAIN
ngrok start voice-gpu
```

### API clients (Pipecat, curl)

Free-plan ngrok shows an interstitial page unless you send:

```
ngrok-skip-browser-warning: true
```

`scripts/test-api.sh` and `pipecat_services/` clients include this when the base URL contains `ngrok`.

### Smoke tests

```bash
./scripts/test-api.sh
```

The script exercises **both voices** (`kelvin`, `lim`) with Singlish sample text and Chatterbox expressive tags (`[chuckle]`, `[laugh]`, `[clear throat]`, `[sigh]`, etc.). See [voices/README.md](voices/README.md#paralinguistic-tags) for all nine supported tags. Outputs land in `.test-output/`:

| File | Test |
|------|------|
| `tts-kelvin.wav` | Kelvin, non-streaming WAV |
| `tts-lim.wav` | Lim, non-streaming WAV |
| `tts-kelvin-stream.pcm` | Kelvin streaming PCM |
| `tts-lim-stream.pcm` | Lim streaming PCM |

STT uploads both `voices/kelvin.wav` and `voices/lim.wav`.

Set `VOICE_GPU_BASE_URL` in your Pipecat bot `.env` to the same `https://…ngrok-free.dev` URL.

## Connect Pipecat

A companion bot is at `pipecat/my-bot-gpu.py`. It uses:

- `VoiceGpuSTTService` — segmented STT over HTTP
- `VoiceGpuTTSService` — streaming TTS over HTTP

LLM is configured in the Pipecat project (`pipecat/.env`), not in this server.

```bash
cd ../pipecat
# Set VOICE_GPU_BASE_URL and VOICE_GPU_API_KEY in pipecat/.env

uv run python my-bot-gpu.py
```

Pipecat service classes live in `pipecat_services/` and are imported via `sys.path` — no fork of Pipecat required.

### Environment variables (Pipecat client)

| Variable | Purpose |
|----------|---------|
| `VOICE_GPU_BASE_URL` | GPU server URL (local or ngrok) |
| `VOICE_GPU_API_KEY` | Must match server key |
| `DEFAULT_VOICE_ID` | Chatterbox voice reference name (`kelvin`, `lim`, etc.) |

## Configuration

See [.env.example](.env.example). Key options:

| Variable | Default | Notes |
|----------|---------|-------|
| `TTS_DEVICE` | `cuda` | Chatterbox device |
| `STT_DEVICE` | `cuda` | Canary device |
| `EAGER_LOAD_MODELS` | `true` | Downloads and loads models at startup |
| `VOICES_DIR` | `./voices` | Reference WAV files |
| `STT_SAMPLE_RATE` | `16000` | Canary expects 16 kHz mono |

## Project layout

```
voice-gpu-server/
├── voice_gpu_server/     # FastAPI app + model loaders
├── pipecat_services/     # Pipecat TTS/STT HTTP clients
├── scripts/start-ngrok.sh
├── voices/               # Custom voice references (*.wav)
├── pyproject.toml
└── README.md
```

## Known blockers / notes

1. **NeMo install** — Canary STT needs NeMo from GitHub; first install can take 10+ minutes.
2. **Chatterbox / perth** — If TTS fails with `'NoneType' object is not callable` at `PerthImplicitWatermarker`, run `./scripts/setup-lightning.sh` (installs `setuptools` + `peft`). The server also applies a no-op watermarker fallback automatically.
3. **CUDA** — CPU fallback is possible for dev (`TTS_DEVICE=cpu`) but too slow for real-time voice.
4. **Chatterbox voice file** — TTS requests fail until `voices/{voice_id}.wav` exists.
5. **VRAM** — Loading both models may need 12–20 GB depending on precision; set `EAGER_LOAD_MODELS=false` to load on first request instead.
6. **Streaming STT** — Canary is batch/segment-based via NeMo `generate()`; Pipecat uses `SegmentedSTTService` with VAD (same pattern as Fal Wizper).
7. **ngrok** — use your static free dev domain (`NGROK_URL`); tunnel must stay running. API clients need `ngrok-skip-browser-warning: true` on free plan.

## Development

```bash
uv sync --extra dev
uv run pytest
```

Health endpoint works without GPU models loaded. With `EAGER_LOAD_MODELS=true` (default), TTS and STT download and load when the server starts.
