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
        """Eager-load models when configured."""
        if settings.eager_load_models:
            logger.info("Eager loading GPU models...")
            await self.tts.load()
            try:
                await self.stt.load()
            except Exception:
                logger.warning("STT model failed to load at startup (TTS may still work)")


model_manager = ModelManager()
