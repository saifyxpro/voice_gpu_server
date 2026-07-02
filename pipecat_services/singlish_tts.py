"""Normalize Singlish particles for Chatterbox TTS (reads 'lah' literally if overused)."""

from __future__ import annotations

import re

# Chatterbox often stresses "lah/lor/leh" as foreign words — strip or soften for speech.
_TRAILING_PARTICLES = re.compile(
    r"\s+(?:lah|lor|leh|la|lo)(?=[,.!?;:\s]|$)",
    re.IGNORECASE,
)
_HOR_QUESTION = re.compile(r"\s+hor\?", re.IGNORECASE)
_HOR_TRAILING = re.compile(r"\s+hor(?=[,.!]|$)", re.IGNORECASE)
_STACKED_AH = re.compile(r"(,\s*ah\b){2,}", re.IGNORECASE)
_TAG_ONLY = re.compile(
    r"^\s*(\[(?:clear throat|sigh|shush|cough|groan|sniff|gasp|chuckle|laugh)\]\s*)+$",
    re.I,
)
# Tool-call / markdown junk the LLM sometimes leaks into spoken output.
_SKIP_LINE = re.compile(r"^[\(\)\[\]{}\s,.:;]+$")
_INLINE_TAG = re.compile(
    r"\[(?:clear throat|sigh|shush|cough|groan|sniff|gasp|chuckle|laugh)\]",
    re.I,
)


def is_skippable_tts_line(text: str) -> bool:
    """Lines that should not be sent to TTS at all."""
    if not text or not text.strip():
        return True
    cleaned = text.strip()
    if _TAG_ONLY.match(cleaned):
        return True
    if _SKIP_LINE.match(cleaned):
        return True
    if len(cleaned) <= 2 and not cleaned.isalnum():
        return True
    return False


def normalize_singlish_for_tts(text: str) -> str:
    """Make Singlish-heavy LLM output sound natural on Chatterbox Turbo."""
    if not text or not text.strip():
        return text

    cleaned = text.strip()

    if _TAG_ONLY.match(cleaned):
        return ""

    # Inline tags must stay on the same line as speech — never synthesize alone.
    if _INLINE_TAG.search(cleaned) and len(_INLINE_TAG.sub("", cleaned).strip()) < 3:
        return ""

    # Drop particles TTS pronounces badly at clause ends.
    cleaned = _TRAILING_PARTICLES.sub("", cleaned)
    cleaned = _HOR_QUESTION.sub(" right?", cleaned)
    cleaned = _HOR_TRAILING.sub(", yeah", cleaned)
    cleaned = _STACKED_AH.sub(", ah", cleaned)

    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r",\s*,", ",", cleaned)
    cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)

    return cleaned.strip()


def prepare_text_for_tts(text: str) -> str:
    """Normalize text before synthesis; return empty string to skip TTS."""
    if is_skippable_tts_line(text):
        return ""
    return normalize_singlish_for_tts(text)
