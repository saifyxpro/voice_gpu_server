"""Canary Qwen STT model wrapper (NVIDIA NeMo SALM)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

from voice_gpu_server.audio_utils import pcm_to_wav, resample_pcm_int16, wav_to_pcm
from voice_gpu_server.config import settings


class CanarySTTModel:
    """Lazy-loaded nvidia/canary-qwen-2.5b via NeMo SALM."""

    def __init__(self, device: str, model_name: str, target_sample_rate: int) -> None:
        self._device = device
        self._model_name = model_name
        self._target_sample_rate = target_sample_rate
        self._model: Any | None = None
        self._lock = asyncio.Lock()
        self._load_error: str | None = None
        self._nemo_available = self._check_nemo()

    @staticmethod
    def _check_nemo() -> bool:
        try:
            import nemo  # noqa: F401

            return True
        except ImportError:
            return False

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def nemo_available(self) -> bool:
        return self._nemo_available

    async def load(self) -> None:
        async with self._lock:
            if self._model is not None:
                return
            if not self._nemo_available:
                msg = (
                    "NeMo is not installed. On the H100 server run:\n"
                    '  uv pip install "nemo_toolkit[asr] @ git+https://github.com/NVIDIA/NeMo.git"'
                )
                self._load_error = msg
                raise RuntimeError(msg)
            try:
                await asyncio.to_thread(self._load_sync)
            except Exception as exc:
                self._load_error = str(exc)
                logger.exception("Failed to load Canary STT")
                raise

    def _load_sync(self) -> None:
        from nemo.collections.speechlm2.models import SALM

        logger.info("Loading Canary STT model={} device={}", self._model_name, self._device)
        self._model = SALM.from_pretrained(self._model_name)
        if self._device.startswith("cuda"):
            self._model = self._model.to(self._device)
        self._model.eval()
        self._load_error = None
        logger.info("Canary STT loaded")

    async def transcribe(self, audio_bytes: bytes) -> str:
        """Transcribe WAV or raw PCM wrapped as WAV."""
        if self._model is None:
            await self.load()

        pcm, sample_rate, _channels = wav_to_pcm(audio_bytes)
        if sample_rate != self._target_sample_rate:
            pcm = resample_pcm_int16(
                pcm, sample_rate, self._target_sample_rate, channels=1
            )

        wav_bytes = pcm_to_wav(pcm, self._target_sample_rate)
        text = await asyncio.to_thread(self._transcribe_sync, wav_bytes)
        return text.strip()

    def _transcribe_sync(self, wav_bytes: bytes) -> str:
        assert self._model is not None

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(wav_bytes)
            wav_path = tmp.name

        try:
            answer_ids = self._model.generate(
                prompts=[
                    [
                        {
                            "role": "user",
                            "content": f"Transcribe the following: {self._model.audio_locator_tag}",
                            "audio": [wav_path],
                        }
                    ]
                ],
                max_new_tokens=256,
            )
            return self._model.tokenizer.ids_to_text(answer_ids[0].cpu())
        finally:
            Path(wav_path).unlink(missing_ok=True)


def create_stt_model() -> CanarySTTModel:
    return CanarySTTModel(
        device=settings.stt_device,
        model_name=settings.stt_model,
        target_sample_rate=settings.stt_sample_rate,
    )
