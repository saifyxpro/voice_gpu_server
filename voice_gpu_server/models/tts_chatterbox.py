"""Chatterbox Turbo TTS model wrapper."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import torch
from loguru import logger

from voice_gpu_server.audio_utils import float_audio_to_pcm16
from voice_gpu_server.config import settings


def _patch_perth_watermarker() -> None:
    """Fix broken resemble-perth when pkg_resources/setuptools is missing (common with uv)."""
    try:
        import setuptools  # noqa: F401 — provides pkg_resources for perth
    except ImportError:
        pass

    try:
        import perth
    except ImportError:
        logger.warning("resemble-perth not installed — Chatterbox may fail to load")
        return

    if perth.PerthImplicitWatermarker is not None:
        return

    logger.warning(
        "perth.PerthImplicitWatermarker is broken — using no-op watermarker. "
        "For full watermarking run: pip install setuptools peft"
    )

    class _NoOpWatermarker:
        def apply_watermark(self, wav, sample_rate=None):
            return wav

    perth.PerthImplicitWatermarker = _NoOpWatermarker


class ChatterboxTTSModel:
    """Lazy-loaded Chatterbox Turbo TTS with cached voice conditionals and streaming."""

    def __init__(self, device: str, voices_dir: Path, default_voice_id: str) -> None:
        self._device = device
        self._voices_dir = voices_dir
        self._default_voice_id = default_voice_id
        self._model: Any | None = None
        self._sample_rate: int | None = None
        self._lock = asyncio.Lock()
        self._sync_lock = threading.Lock()
        self._load_error: str | None = None
        self._voice_conds: dict[str, Any] = {}

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
        _patch_perth_watermarker()
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        logger.info("Loading Chatterbox Turbo on device={}", self._device)
        self._model = ChatterboxTurboTTS.from_pretrained(device=self._device)
        self._sample_rate = int(self._model.sr)
        from voice_gpu_server.chatterbox_streaming import _patch_chatterbox_flow_streaming

        _patch_chatterbox_flow_streaming()
        self._load_error = None
        logger.info("Chatterbox Turbo loaded (sample_rate={})", self._sample_rate)

    async def prepare_all_voices(self) -> None:
        """Pre-compute voice conditionals at startup to skip per-request librosa/encoder work."""
        if self._model is None:
            await self.load()

        for voice_id, path in self.list_voices():
            await asyncio.to_thread(self._ensure_voice_conditionals_sync, voice_id, str(path))

    def _ensure_voice_conditionals_sync(self, voice_id: str, voice_path: str) -> None:
        assert self._model is not None
        cached = self._voice_conds.get(voice_id)
        if cached is not None:
            self._model.conds = cached
            return

        with self._sync_lock:
            cached = self._voice_conds.get(voice_id)
            if cached is not None:
                self._model.conds = cached
                return

            logger.info("Preparing Chatterbox conditionals for voice={}", voice_id)
            with torch.inference_mode():
                self._model.prepare_conditionals(
                    voice_path,
                    exaggeration=settings.tts_exaggeration,
                    norm_loudness=settings.tts_norm_loudness,
                )
            self._voice_conds[voice_id] = self._model.conds

    def _activate_voice_sync(self, voice_id: str, voice_path: str) -> None:
        self._ensure_voice_conditionals_sync(voice_id, voice_path)

    def _generation_kwargs(self) -> dict[str, Any]:
        return {
            "temperature": settings.tts_temperature,
            "top_p": settings.tts_top_p,
            "top_k": settings.tts_top_k,
            "repetition_penalty": settings.tts_repetition_penalty,
        }

    async def synthesize(self, text: str, voice_id: str | None) -> tuple[bytes, int]:
        """Return 16-bit mono PCM and sample rate."""
        if self._model is None:
            await self.load()

        vid = voice_id or self._default_voice_id
        voice_path = self.resolve_voice_path(voice_id)
        pcm, sample_rate = await asyncio.to_thread(
            self._synthesize_sync, text, vid, str(voice_path)
        )
        return pcm, sample_rate

    async def synthesize_stream(self, text: str, voice_id: str | None) -> AsyncIterator[bytes]:
        """Yield PCM chunks as audio is generated (low TTFB)."""
        if self._model is None:
            await self.load()

        vid = voice_id or self._default_voice_id
        voice_path = self.resolve_voice_path(voice_id)
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=16)
        loop = asyncio.get_running_loop()

        def _producer() -> None:
            try:
                for chunk in self._iter_pcm_chunks_sync(text, vid, str(voice_path)):
                    asyncio.run_coroutine_threadsafe(queue.put(chunk), loop).result()
            except Exception as exc:
                logger.exception("TTS streaming failed")
                asyncio.run_coroutine_threadsafe(queue.put(exc), loop).result()
            else:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop).result()

        thread = threading.Thread(target=_producer, daemon=True)
        thread.start()

        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item

        await asyncio.to_thread(thread.join)

    def _iter_pcm_chunks_sync(self, text: str, voice_id: str, voice_path: str) -> Iterator[bytes]:
        assert self._model is not None
        with self._sync_lock:
            self._activate_voice_sync(voice_id, voice_path)

            if hasattr(self._model, "stream"):
                yield from self._stream_via_native_api(text)
                return

            yield from self._stream_pcm_chunks(text)

    def _stream_pcm_chunks(self, text: str) -> Iterator[bytes]:
        from voice_gpu_server.chatterbox_streaming import stream_turbo_pcm

        assert self._model is not None
        try:
            yield from stream_turbo_pcm(
                self._model,
                text,
                chunk_tokens=settings.tts_stream_chunk_tokens,
                crossfade_ms=settings.tts_stream_crossfade_ms,
                max_gen_len=settings.tts_max_gen_len,
                n_cfm_timesteps=settings.tts_n_cfm_timesteps,
                **self._generation_kwargs(),
            )
        except Exception as exc:
            logger.warning("TTS streaming failed ({}), using batch generate fallback", exc)
            pcm, _ = self._synthesize_batch_pcm(text)
            step = max(1, settings.tts_stream_chunk_tokens * 480)
            for offset in range(0, len(pcm), step):
                yield pcm[offset : offset + step]

    def _synthesize_batch_pcm(self, text: str) -> tuple[bytes, int]:
        """Batch generate full utterance (watermarked path)."""
        assert self._model is not None
        with torch.inference_mode():
            wav = self._model.generate(
                text,
                norm_loudness=settings.tts_norm_loudness,
                **self._generation_kwargs(),
            )
        if isinstance(wav, torch.Tensor):
            pcm = float_audio_to_pcm16(wav)
        else:
            audio = np.clip(np.asarray(wav).squeeze(), -1.0, 1.0)
            pcm = (audio * 32767).astype(np.int16).tobytes()
        return pcm, int(self._model.sr)

    def _stream_via_native_api(self, text: str) -> Iterator[bytes]:
        """Use upstream ``ChatterboxTurboTTS.stream()`` when available."""
        assert self._model is not None
        kwargs = {
            **self._generation_kwargs(),
            "chunk_tokens": settings.tts_stream_chunk_tokens,
            "crossfade_ms": settings.tts_stream_crossfade_ms,
            "max_gen_len": settings.tts_max_gen_len,
            "norm_loudness": settings.tts_norm_loudness,
        }
        with torch.inference_mode():
            for chunk in self._model.stream(text, **kwargs):
                yield float_audio_to_pcm16(chunk.audio)

    def _synthesize_sync(self, text: str, voice_id: str, voice_path: str) -> tuple[bytes, int]:
        assert self._model is not None
        with self._sync_lock:
            self._activate_voice_sync(voice_id, voice_path)
            pcm, sample_rate = self._synthesize_batch_pcm(text)
            return pcm, sample_rate


def create_tts_model() -> ChatterboxTTSModel:
    return ChatterboxTTSModel(
        device=settings.tts_device,
        voices_dir=settings.voices_dir,
        default_voice_id=settings.default_voice_id,
    )
