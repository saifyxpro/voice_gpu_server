"""Singleton model registry."""

from __future__ import annotations

from loguru import logger

from voice_gpu_server.config import settings
from voice_gpu_server.models.stt_canary import CanarySTTModel, create_stt_model
from voice_gpu_server.models.tts_chatterbox import ChatterboxTTSModel, create_tts_model


class ModelManager:
    """Coordinates lazy/eager loading of TTS and STT models."""

    def __init__(self) -> None:
        self.tts: ChatterboxTTSModel = create_tts_model()
        self.stt: CanarySTTModel = create_stt_model()

    async def warmup(self) -> None:
        """Load GPU models at startup (downloads weights on first run)."""
        if not settings.eager_load_models:
            logger.info("EAGER_LOAD_MODELS=false — models load on first API request")
            return

        logger.info("Eager loading Chatterbox TTS (may download from Hugging Face)...")
        await self.tts.load()
        logger.info("Chatterbox TTS ready (sample_rate={})", self.tts.sample_rate)

        logger.info("Preparing Chatterbox voice conditionals...")
        await self.tts.prepare_all_voices()

        logger.info("Eager loading Canary STT (may download from Hugging Face)...")
        try:
            await self.stt.load()
            logger.info("Canary STT ready")
        except Exception as exc:
            logger.warning("STT failed at startup: {} — TTS will still work", exc)


model_manager = ModelManager()
