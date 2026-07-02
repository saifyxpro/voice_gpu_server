"""HTTP STT client for voice-gpu-server (Canary Qwen)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

import aiohttp
from loguru import logger

from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601
from pipecat.utils.tracing.service_decorators import traced_stt


@dataclass
class VoiceGpuSTTSettings(STTSettings):
    """Settings for VoiceGpuSTTService."""

    pass


class VoiceGpuSTTService(SegmentedSTTService):
    """Segmented speech-to-text via the local/H100 voice-gpu-server HTTP API."""

    Settings = VoiceGpuSTTSettings
    _settings: Settings

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        aiohttp_session: Optional[aiohttp.ClientSession] = None,
        sample_rate: Optional[int] = None,
        settings: Optional[Settings] = None,
        ttfs_p99_latency: Optional[float] = 1.5,
        **kwargs,
    ):
        default_settings = self.Settings(
            model=None,
            language=Language.EN,
        )
        if settings is not None:
            default_settings.apply_update(settings)

        super().__init__(
            sample_rate=sample_rate,
            ttfs_p99_latency=ttfs_p99_latency,
            settings=default_settings,
            **kwargs,
        )

        self._base_url = (base_url or os.getenv("VOICE_GPU_BASE_URL", "http://127.0.0.1:8765")).rstrip(
            "/"
        )
        self._api_key = api_key or os.getenv("VOICE_GPU_API_KEY")
        self._session = aiohttp_session
        self._owns_session = aiohttp_session is None

    def can_generate_metrics(self) -> bool:
        return True

    def language_to_service_language(self, language: Language) -> Optional[str]:
        return "en"

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if "ngrok" in self._base_url:
            headers["ngrok-skip-browser-warning"] = "true"
        return headers

    @traced_stt
    async def _handle_transcription(
        self, transcript: str, is_final: bool, language: Optional[str] = None
    ):
        await self.stop_processing_metrics()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        """POST WAV segment to GPU STT server."""
        try:
            await self.start_processing_metrics()
            session = await self._get_session()

            form = aiohttp.FormData()
            form.add_field(
                "file",
                audio,
                filename="segment.wav",
                content_type="audio/wav",
            )

            async with session.post(
                f"{self._base_url}/v1/stt",
                data=form,
                headers=self._headers(),
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    yield ErrorFrame(error=f"GPU STT error ({response.status}): {error_text}")
                    return
                result = await response.json()

            text = (result.get("text") or "").strip()
            if text:
                await self._handle_transcription(text, True, self._settings.language)
                logger.debug(f"Transcription: [{text}]")
                yield TranscriptionFrame(
                    text,
                    self._user_id,
                    time_now_iso8601(),
                    Language(self._settings.language),
                    result=result,
                )
        except Exception as exc:
            yield ErrorFrame(error=f"GPU STT request failed: {exc}")

    async def cleanup(self):
        await super().cleanup()
        if self._owns_session and self._session:
            await self._session.close()
            self._session = None
