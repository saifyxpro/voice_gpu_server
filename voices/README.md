# Custom voice references for Chatterbox Turbo

Chatterbox Turbo requires a **~10 second reference WAV clip** for zero-shot voice cloning.

## Add a voice

1. Record or export a clean mono WAV clip (~10s, minimal background noise).
2. Save it as `{voice_id}.wav` in this directory.

Example:

```bash
cp /path/to/my-speaker-clip.wav voices/default.wav
```

3. Set `DEFAULT_VOICE_ID=default` in `.env` (or pass `voice_id` in TTS requests).

## Paralinguistic tags

Both TTS backends support inline expressive tags, but **syntax differs by provider**. Use the tags that match whichever system you are calling.

### Chatterbox Turbo

- `[cough]`, `[laugh]`, `[chuckle]`

Example:

```
Hi there, Sarah here [chuckle], do you have a minute to chat?
```

### ElevenLabs v3 (audio tags)

Eleven v3 uses lowercase square-bracket tags as natural-language delivery cues. Common tags for outbound voice samples:

- **Emotions / delivery:** `[curious]`, `[excited]`, `[thoughtful]`, `[happy]`, `[whispers]`, `[sarcastic]`
- **Human reactions:** `[laughs]`, `[chuckles]`, `[sighs]`, `[clears throat]`, `[exhales]`
- **Pacing:** `[short pause]`, `[long pause]`

Example:

```
Hi there, Sarah here [chuckles], do you have a minute to chat?
```

> **Note:** The sample scripts below use **ElevenLabs v3** tag syntax. If you are testing with Chatterbox, swap equivalents where needed (e.g. `[chuckles]` → `[chuckle]`, `[laughs]` → `[laugh]`).

## API

List registered voices:

```bash
curl -H "Authorization: Bearer $VOICE_GPU_API_KEY" \
  http://localhost:8765/v1/voices
```

Use a specific voice:

```bash
curl -X POST http://localhost:8765/v1/tts \
  -H "Authorization: Bearer $VOICE_GPU_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello [laugh]","voice_id":"default","stream":false,"response_format":"wav"}'
```

## Sample texts (20–30 seconds)

Use these scripts when **recording a reference clip** or **generating a test sample**. Each block is roughly 20–30 seconds at a natural speaking pace (~150 words per minute).

> **Tip:** For the reference WAV, trim a clean ~10 second slice from one of these recordings. For full TTS tests, paste the whole block.

### Sample 1 — Neutral / general

```
Good morning. [clears throat] My name is Alex — I'm calling to follow up on your recent enquiry, ah. [curious] I wanted to check whether you got any questions about the information we sent over last week. If now not a good time, I can call back later lor — [thoughtful] just let me know what works best for you. Otherwise, I'm happy to walk through the details right now.
```

### Sample 2 — Outbound caller (professional, warm)

```
Hi, this is Sarah calling from One CoSec, ah. I'm reaching out because we noticed your company may be due for its annual filing soon lor. We help businesses stay compliant without the paperwork headache. [curious] Got two minutes for me to explain how we can support you or not? No pressure at all — [chuckles] I just want to make sure you don't miss any important deadlines lah.
```

### Sample 3 — Conversational with expressive tags

```
Hey there [chuckles], thanks for picking up, ah. So, I was looking at your account and thought I'll give you a quick ring. Nothing urgent lah — just wanted to check everything running smoothly on your end or not. [curious] If you got a minute, I can share a couple of updates that might save you some time this month hor. What do you think?
```

### Sample 4 — Singlish / local tone (One CoSec style)

```
Hi, good afternoon. This is Kevin from One CoSec, ah. I'm calling to touch base on your corporate secretary matters — got a few reminders about your AGM and filing dates lor. [sighs] Don't worry lah, quite straightforward one. You free now to talk, or [curious] you prefer I send everything by email instead hor?
```

### Sample 5 — Singlish reminder call (One CoSec style)

```
Hello, Kevin here from One CoSec again, ah. [clears throat] Just a gentle reminder leh — your annual return deadline coming up already, so I thought I'll give you a quick call. Nothing to panic about lah. [chuckles] If you already submitted, can let me know hor? Otherwise I can walk you through the steps now — you got five minutes or not?
```

#### Singlish notes for TTS

These samples use a **bridge register**: Standard English backbone with light local particles, suitable for warm outbound calls to Singapore SMEs (not heavy hawker-centre Singlish). Samples 1–2 lean slightly more formal; samples 3–5 are more conversational.

- **Particles (clause-final, short):** *lah* softens and reassures ("Don't worry lah"); *lor* marks something as matter-of-fact ("…filing dates lor"); *leh* makes a suggestion tentative ("reminder leh"); *ah* warms openers and tags ("One CoSec, ah"); *hor* checks agreement ("…by email instead hor").
- **Grammar patterns:** topic-prominent drops ("everything running smoothly", "You free now"); *got* for possession ("got a few reminders"); *one* as a classifier ("straightforward one"); *already* for imminent or completed state ("deadline coming up already"); *or not* / *can or not* for yes–no checks.
- **Delivery cues:** Place particles at the **end of clauses**, not mid-sentence. Avoid stacking more than two particles in one utterance. ElevenLabs v3 tags like `[sighs]`, `[chuckles]`, and `[curious]` work best on the Standard English phrases around the particles.
- **Professional boundary:** Keep filing/compliance wording clear and standard; use Singlish for rapport and pacing, not for legal terms. Omit heavy slang (*sia*, *walao*, *paiseh*) in business outbound scripts.

### Recording tips

- Speak at your normal outbound-call pace — not too fast, not too slow.
- Use a quiet room; avoid echo, fan noise, and keyboard clicks.
- Keep volume consistent; don't whisper or shout.
- Pause briefly at commas and full stops so the model learns natural rhythm.
- Export as **mono WAV**, 16-bit or 24-bit, 22050 Hz or 44100 Hz.
