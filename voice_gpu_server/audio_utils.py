"""Shared audio helpers."""

from __future__ import annotations

import io
import wave
from typing import Iterator

import numpy as np
from scipy import signal


def pcm_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Wrap 16-bit PCM bytes in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def wav_to_pcm(wav_bytes: bytes) -> tuple[bytes, int, int]:
    """Extract PCM, sample rate, and channels from WAV bytes."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        pcm = wav.readframes(wav.getnframes())
    return pcm, sample_rate, channels


def resample_pcm_int16(
    pcm: bytes, source_rate: int, target_rate: int, channels: int = 1
) -> bytes:
    """Resample 16-bit PCM audio."""
    if source_rate == target_rate:
        return pcm

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    ratio = target_rate / source_rate
    new_length = int(len(samples) * ratio)
    resampled = signal.resample(samples, new_length)
    resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
    return resampled.tobytes()


def chunk_bytes(data: bytes, chunk_size: int = 8192) -> Iterator[bytes]:
    """Yield fixed-size byte chunks."""
    for offset in range(0, len(data), chunk_size):
        yield data[offset : offset + chunk_size]
