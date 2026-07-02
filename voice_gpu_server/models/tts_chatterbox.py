"""Chatterbox Turbo TTS model wrapper."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import numpy as np
import torch
from loguru import logger

from voice_gpu_server.config import settings


class ChatterboxTTSModel:
    """Lazy-loaded Chatterbox Turbo TTS."""

    def __init__(self, device: str, voices_dir: Path, default_voice_id: str) -> None:
        self._device = device
        self._voices_dir = voices_dir
        self._default_voice_id = default_voice_id
        self._model: Any | None = None
        self._sample_rate: int | None = None
        self._lock = asyncio.Lock()
        self._load_error: str | None = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def sample_rate(self) -> int | None:
        return self._sample_rate

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def resolve_voice_path(self, voice_id: str | None) -> Path:
        """Resolve voice reference WAV for cloning."""
        vid = voice_id or self._default_voice_id
        candidate = self._voices_dir / f"{vid}.wav"
        if candidate.exists():
            return candidate

        default = self._voices_dir / f"{self._default_voice_id}.wav"
        if default.exists():
            logger.warning(
                "Voice '{}' not found; falling back to '{}'", vid, self._default_voice_id
            )
            return default

        raise FileNotFoundError(
            f"No voice reference at {candidate}. "
            f"Add a ~10s WAV clip as voices/{vid}.wav (see voices/README.md)."
        )

    def list_voices(self) -> list[tuple[str, Path]]:
        self._voices_dir.mkdir(parents=True, exist_ok=True)
        voices: list[tuple[str, Path]] = []
        for path in sorted(self._voices_dir.glob("*.wav")):
            voices.append((path.stem, path))
        return voices

    async def load(self) -> None:
        async with self._lock:
            if self._model is not None:
                return
            try:
                await asyncio.to_thread(self._load_sync)
            except Exception as exc:
                self._load_error = str(exc)
                logger.exception("Failed to load Chatterbox TTS")
                raise

    def _load_sync(self) -> None:
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        logger.info("Loading Chatterbox Turbo on device={}", self._device)
        self._model = ChatterboxTurboTTS.from_pretrained(device=self._device)
        self._sample_rate = int(self._model.sr)
        self._load_error = None
        logger.info("Chatterbox Turbo loaded (sample_rate={})", self._sample_rate)

    async def synthesize(self, text: str, voice_id: str | None) -> tuple[bytes, int]:
        """Return 16-bit mono PCM and sample rate."""
        if self._model is None:
            await self.load()

        voice_path = self.resolve_voice_path(voice_id)
        pcm, sample_rate = await asyncio.to_thread(
            self._synthesize_sync, text, str(voice_path)
        )
        return pcm, sample_rate

    def _synthesize_sync(self, text: str, audio_prompt_path: str) -> tuple[bytes, int]:
        assert self._model is not None
        wav = self._model.generate(text, audio_prompt_path=audio_prompt_path)

        if isinstance(wav, torch.Tensor):
            audio = wav.detach().cpu().numpy()
        else:
            audio = np.asarray(wav)

        if audio.ndim > 1:
            audio = audio.squeeze()

        audio = np.clip(audio, -1.0, 1.0)
        pcm = (audio * 32767).astype(np.int16).tobytes()
        return pcm, int(self._model.sr)


def create_tts_model() -> ChatterboxTTSModel:
    return ChatterboxTTSModel(
        device=settings.tts_device,
        voices_dir=settings.voices_dir,
        default_voice_id=settings.default_voice_id,
    )
