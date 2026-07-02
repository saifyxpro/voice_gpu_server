---
name: chatterbox-paralinguistic-tags
description: Writes Chatterbox Turbo TTS scripts with correct paralinguistic tag syntax and sparing, natural placement. Use when drafting outbound call scripts, Pipecat bot lines, test-api text, voices/README samples, or any Chatterbox Turbo prompt for voice-gpu-server.
---

# Chatterbox Paralinguistic Tags

## Core rule

**Use tags like seasoning, not sauce.** fal and Resemble recommend sparing use — overuse sounds theatrical and hurts professional outbound calls.

Default for One CoSec / voice-agent scripts: **0–1 tag per spoken turn**. Two tags only when the emotional beat clearly changes mid-turn and clauses are far apart.

## Budget (enforce these)

| Script length | Max tags | Notes |
|---------------|----------|-------|
| Short line (<20 words) | **0–1** | Often zero is better |
| One call turn (~30–80 words) | **1** | `[chuckle]` or `[sigh]` typical |
| Long script (20–30 s) | **1–2** | Never more than 2 |
| API smoke test | **1** | Prove tags work; don't stack |
| Dev tag audit | **1 per request** | One tag per isolated test utterance |

**Never** pack multiple tags into production scripts. **Never** use all nine tags in one passage.

## Supported tags (exact spelling)

`[clear throat]` `[sigh]` `[shush]` `[cough]` `[groan]` `[sniff]` `[gasp]` `[chuckle]` `[laugh]`

- Lowercase only, square brackets, copy exactly (`[chuckle]` not `[chuckles]`).
- Turbo only — unknown tags are read aloud as words.

Full per-tag guidance: [reference.md](reference.md)

## What to use when (outbound voice)

| Situation | Preferred tag | Avoid |
|-----------|---------------|-------|
| Warm open / light rapport | `[chuckle]` | `[laugh]` (too strong for compliance calls) |
| Empathy, hassle acknowledged | `[sigh]` | `[groan]` in professional context |
| Start of formal line | `[clear throat]` | More than once per call |
| Real surprise (deadline missed) | `[gasp]` | Stacking with `[sigh]` in same sentence |
| Confidential aside | `[shush]` | In normal business flow |
| Comedy / punchline | `[laugh]` | Multiple laughs in one turn |

**Default choice for One CoSec outbound:** `[chuckle]` once, or no tag.

## Placement

- Put tags at **clause boundaries** — where a human would breathe or react.
- Good: `Hi, Kevin from One CoSec, ah [chuckle]. Got two minutes or not?`
- Bad: `Hi [chuckle] Kevin [sigh] from [chuckle] One CoSec`
- Don't place mid-word. Don't repeat the same tag back-to-back.

## Singlish + tags

Keep particles (*lah*, *lor*, *hor*, *ah*) in spoken text. Put the tag on the English phrase around them, usually once per turn:

```
Nothing to panic about lah [chuckle]. Can walk you through it now hor?
```

## Do / don't

**Do**
- Prefer plain spoken text; add a tag only when delivery needs a human beat
- Match tag to tone (`[sigh]` with empathy, not with excitement)
- Test one tag placement if unsure

**Don't**
- Stack tags in one sentence
- Use tags in every test script or sample by default
- Use `[laugh]` + `[chuckle]` in the same turn
- Use ElevenLabs syntax (`[chuckles]`, `[clears throat]`, `[curious]`) — Chatterbox won't interpret them

## Workflow for new scripts

1. Write the line **without** tags.
2. Ask: does this need one human reaction? If no → ship tag-free.
3. If yes → pick **one** tag from the table above.
4. Count tags — if >1 per turn, remove until ≤1 (≤2 only for long scripts).
5. Read aloud; if it sounds performative, remove the tag.

## Examples

**Good — one tag, outbound reminder**
```
Hello, Kevin here from One CoSec again, ah. Just a gentle reminder leh — your annual return deadline coming up already. Nothing to panic about lah [chuckle]. You got five minutes or not?
```

**Good — no tags (often best)**
```
Hi, good afternoon. This is Kevin from One CoSec, ah. Got a few reminders about your AGM and filing dates lor. Don't worry lah, quite straightforward one.
```

**Bad — over-tagged**
```
[clear throat] Hi [chuckle] from One CoSec [sigh] deadline tomorrow [gasp] [groan] still got time [laugh]
```

## Dev-only: testing a single tag

To verify one tag in isolation (not for production copy):

```bash
curl -X POST "$VOICE_GPU_BASE_URL/v1/tts" \
  -H "Authorization: Bearer $VOICE_GPU_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"Quick test [sigh] — can you hear that?","voice_id":"kelvin","stream":false,"response_format":"wav"}'
```

Run **one tag per request** when auditing sound quality.

## Sources

- [fal Chatterbox Turbo blog](https://blog.fal.ai/chatterbox-turbo-is-now-available-on-fal/) — use sparingly; one `[chuckle]` or `[sigh]` goes a long way
- [Chatterbox Turbo on fal](https://fal.ai/models/fal-ai/chatterbox/text-to-speech/turbo) — full tag list
- [ResembleAI/chatterbox](https://github.com/resemble-ai/chatterbox) — Turbo paralinguistic tags
