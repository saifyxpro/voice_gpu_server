# Custom voice references for Chatterbox Turbo

Chatterbox Turbo uses **zero-shot voice cloning**: you pass a short reference WAV and the model speaks new text in that speaker's voice. No fine-tuning required.

## How Chatterbox custom voice works

Per [ResembleAI/chatterbox-turbo](https://huggingface.co/ResembleAI/chatterbox-turbo):

1. **Reference clip** — a clean **~10 second** mono WAV of the target speaker (minimal background noise).
2. **Generate** — Chatterbox clones the voice at inference time via `audio_prompt_path`:

```python
from chatterbox.tts_turbo import ChatterboxTurboTTS

model = ChatterboxTurboTTS.from_pretrained(device="cuda")
wav = model.generate(
    "Hi there, Sarah here [chuckle], do you have a minute?",
    audio_prompt_path="voices/kelvin.wav",
)
```

3. **Paralinguistic tags** — Turbo supports nine inline tags (see [Paralinguistic tags](#paralinguistic-tags) below).

### This repo's voices

| `voice_id` | File | Use |
|------------|------|-----|
| `kelvin` | `voices/kelvin.wav` | Kevin-style outbound caller |
| `lim` | `voices/lim.wav` | Lim-style outbound caller |

Pass `voice_id` per request, or set `DEFAULT_VOICE_ID=kelvin` in `.env`.

## Add a voice

1. Record or export a clean mono WAV clip (~10s, minimal background noise).
2. Save it as `{voice_id}.wav` in this directory.

Example:

```bash
cp /path/to/speaker-clip.wav voices/kelvin.wav
```

3. Set `DEFAULT_VOICE_ID=kelvin` in `.env` (optional), or pass `voice_id` in each TTS request.

### API examples

List voices:

```bash
curl -H "Authorization: Bearer $VOICE_GPU_API_KEY" \
  http://localhost:8765/v1/voices
```

TTS with a specific voice:

```bash
curl -X POST http://localhost:8765/v1/tts \
  -H "Authorization: Bearer $VOICE_GPU_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"Hi, Kevin from One CoSec, ah [chuckle].","voice_id":"kelvin","stream":false,"response_format":"wav"}'
```

Pipecat bot — set in `.env`:

```bash
DEFAULT_VOICE_ID=kelvin   # or lim
```

Or in `my-bot-gpu.py` via `VoiceGpuTTSService(voice_id="lim", ...)`.

## Paralinguistic tags

Chatterbox **Turbo** generates non-speech vocal reactions directly from inline text tags — laughs, sighs, coughs, and more — in the **same cloned voice**, with no post-processing or audio splicing.

> **Turbo only.** These tags work with `ChatterboxTurboTTS` (this server). Other Chatterbox variants read unknown tags aloud as plain words.

### Supported tags (complete list)

Exact spelling matters — lowercase, square brackets, as written:

| Tag | Effect | Good for |
|-----|--------|----------|
| `[clear throat]` | Throat clear / reset before speaking | Opening a call, before an important line |
| `[sigh]` | Audible sigh (relief, tiredness, empathy) | Softening bad news, acknowledging hassle |
| `[shush]` | Quiet “shh” | Confidential aside, calming moment |
| `[cough]` | Short cough | Natural pause, getting attention |
| `[groan]` | Groan / mild frustration | Reacting to complexity or delay |
| `[sniff]` | Sniff | Emotional beat, slight hesitation |
| `[gasp]` | Quick gasp | Surprise, mild shock |
| `[chuckle]` | Light laugh | Warm rapport, soft humour |
| `[laugh]` | Fuller laugh | Stronger amusement |

Source: [Chatterbox Turbo Gradio demo](https://github.com/resemble-ai/chatterbox/blob/master/gradio_tts_turbo_app.py) and [fal model docs](https://fal.ai/models/fal-ai/chatterbox/text-to-speech/turbo).

### Syntax rules

1. **Copy tags exactly** — `[clear throat]` not `[clears throat]`; `[chuckle]` not `[chuckles]`; `[sigh]` not `[sighs]`.
2. **Lowercase only** — `[Laugh]` and `[CHUCKLE]` are not supported.
3. **Place at natural boundaries** — before or after a clause where a human would react, not mid-word.
4. **Use sparingly** — **0–1 tag per call turn** for outbound scripts; max 2 on a long (~30 s) script. Overuse sounds theatrical (see `.cursor/skills/chatterbox-paralinguistic-tags/SKILL.md`).
5. **Singlish + tags** — keep particles (*lah*, *lor*, *hor*) in the spoken text; at most one tag on the English phrases around them.

### Examples

Short:

```
Hi there, Sarah here [chuckle], do you have a minute to chat?
```

Outbound call (One CoSec style) — **one tag**:

```
Hi, good afternoon. This is Kevin from One CoSec, ah. Got a few reminders about your AGM and filing dates lor. Don't worry lah, quite straightforward one [chuckle]. You free now to talk or not?
```

Surprise / empathy — **one tag**:

```
Oh, your deadline was yesterday? [gasp] Okay okay, we can still fix this — let me walk you through it now.
```

API request:

```bash
curl -X POST http://localhost:8765/v1/tts \
  -H "Authorization: Bearer $VOICE_GPU_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"Hi, Kevin from One CoSec, ah [chuckle]. Got two minutes or not?","voice_id":"kelvin","stream":false,"response_format":"wav"}'
```

> **Agent skill:** `.cursor/skills/chatterbox-paralinguistic-tags/` — when writing scripts, follow the sparing-use budgets there (don't stack tags).

### Chatterbox vs ElevenLabs v3

This server uses **Chatterbox Turbo**. If you also write scripts for ElevenLabs v3, tag syntax differs:

| Chatterbox Turbo | ElevenLabs v3 (not on this server) |
|------------------|-------------------------------------|
| `[clear throat]` | `[clears throat]` |
| `[chuckle]` | `[chuckles]` |
| `[laugh]` | `[laughs]` |
| `[sigh]` | `[sighs]` |
| `[gasp]`, `[cough]`, `[groan]`, `[sniff]`, `[shush]` | — (no direct equivalent) |
| — | `[curious]`, `[excited]`, `[thoughtful]`, `[whispers]` (delivery cues) |

ElevenLabs v3 adds **emotion/delivery** tags Chatterbox does not support — those are read as plain text by Turbo. For Pipecat + this GPU server, stick to the nine Chatterbox tags above.

### ElevenLabs v3 reference (other pipelines)

If you use Eleven v3 elsewhere, common tags include:

- **Emotions / delivery:** `[curious]`, `[excited]`, `[thoughtful]`, `[happy]`, `[whispers]`, `[sarcastic]`
- **Human reactions:** `[laughs]`, `[chuckles]`, `[sighs]`, `[clears throat]`, `[exhales]`
- **Pacing:** `[short pause]`, `[long pause]`

## Sample texts (20–30 seconds)

Use these scripts when **recording a reference clip** or **generating a test sample**. Each block is roughly 20–30 seconds at a natural speaking pace (~150 words per minute).

> **Tip:** For the reference WAV, trim a clean ~10 second slice from one of these recordings. For full TTS tests, paste the whole block. Tags use **Chatterbox Turbo** syntax.

### Sample 1 — Neutral / general

```
Good morning. My name is Alex — I'm calling to follow up on your recent enquiry, ah. I wanted to check whether you got any questions about the information we sent over last week. If now not a good time, I can call back later lor — just let me know what works best for you.
```

### Sample 2 — Outbound caller (professional, warm)

```
Hi, this is Sarah calling from One CoSec, ah. I'm reaching out because we noticed your company may be due for its annual filing soon lor. We help businesses stay compliant without the paperwork headache. Got two minutes for me to explain how we can support you or not? No pressure at all — [chuckle] I just want to make sure you don't miss any important deadlines lah.
```

### Sample 3 — Conversational with expressive tags

```
Hey there, thanks for picking up, ah. So, I was looking at your account and thought I'll give you a quick ring. Nothing urgent lah — just wanted to check everything running smoothly on your end or not. If you got a minute, I can share a couple of updates that might save you some time this month hor. What do you think?
```

### Sample 4 — Singlish / local tone (One CoSec style)

```
Hi, good afternoon. This is Kevin from One CoSec, ah. I'm calling to touch base on your corporate secretary matters — got a few reminders about your AGM and filing dates lor. Don't worry lah, quite straightforward one. You free now to talk, or you prefer I send everything by email instead hor?
```

### Sample 5 — Singlish reminder call (One CoSec style)

```
Hello, Kevin here from One CoSec again, ah. Just a gentle reminder leh — your annual return deadline coming up already, so I thought I'll give you a quick call. Nothing to panic about lah [chuckle]. If you already submitted, can let me know hor? Otherwise I can walk you through the steps now — you got five minutes or not?
```

#### Singlish notes for TTS

These samples use a **bridge register**: Standard English backbone with light local particles, suitable for warm outbound calls to Singapore SMEs (not heavy hawker-centre Singlish). Samples 1–2 lean slightly more formal; samples 3–5 are more conversational.

- **Particles (clause-final, short):** *lah* softens and reassures ("Don't worry lah"); *lor* marks something as matter-of-fact ("…filing dates lor"); *leh* makes a suggestion tentative ("reminder leh"); *ah* warms openers and tags ("One CoSec, ah"); *hor* checks agreement ("…by email instead hor").
- **Grammar patterns:** topic-prominent drops ("everything running smoothly", "You free now"); *got* for possession ("got a few reminders"); *one* as a classifier ("straightforward one"); *already* for imminent or completed state ("deadline coming up already"); *or not* / *can or not* for yes–no checks.
- **Delivery cues:** Place particles at the **end of clauses**, not mid-sentence. Avoid stacking more than two particles in one utterance. Chatterbox tags like `[sigh]`, `[chuckle]`, and `[clear throat]` work best on the Standard English phrases around the particles.
- **Professional boundary:** Keep filing/compliance wording clear and standard; use Singlish for rapport and pacing, not for legal terms. Omit heavy slang (*sia*, *walao*, *paiseh*) in business outbound scripts.

### Recording tips

- Speak at your normal outbound-call pace — not too fast, not too slow.
- Use a quiet room; avoid echo, fan noise, and keyboard clicks.
- Keep volume consistent; don't whisper or shout.
- Pause briefly at commas and full stops so the model learns natural rhythm.
- Export as **mono WAV**, 16-bit or 24-bit, 22050 Hz or 44100 Hz.
