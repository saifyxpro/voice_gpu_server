"""HTTP TTS client for voice-gpu-server (Chatterbox Turbo)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

import aiohttp
from loguru import logger

from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.tracing.service_decorators import traced_tts


@dataclass
class VoiceGpuTTSSettings(TTSSettings):
    """Settings for VoiceGpuTTSService."""

    pass


class VoiceGpuTTSService(TTSService):
    """Text-to-speech via the local/H100 voice-gpu-server HTTP API."""

    Settings = VoiceGpuTTSSettings
    _settings: Settings

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
        aiohttp_session: Optional[aiohttp.ClientSession] = None,
        sample_rate: Optional[int] = 24000,
        settings: Optional[Settings] = None,
        **kwargs,
    ):
        default_settings = self.Settings(
            model=None,
            voice=voice_id,
            language=Language.EN,
        )
        if settings is not None:
            default_settings.apply_update(settings)

        super().__init__(
            sample_rate=sample_rate,
            push_start_frame=True,
            push_stop_frames=True,
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
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if "ngrok" in self._base_url:
            headers["ngrok-skip-browser-warning"] = "true"
        return headers

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        """Stream PCM audio from the GPU TTS server."""
        logger.debug(f"{self}: Generating TTS [{text}]")

        async for frame in self._run_tts_request(text, context_id, stream=True):
            if isinstance(frame, ErrorFrame):
                logger.warning(f"{self}: streaming failed, retrying non-streaming — {frame.error}")
                async for retry_frame in self._run_tts_request(text, context_id, stream=False):
                    yield retry_frame
                return
            yield frame

    async def _run_tts_request(
        self, text: str, context_id: str, *, stream: bool
    ) -> AsyncGenerator[Frame, None]:
        payload = {
            "text": text,
            "voice_id": self._settings.voice,
            "stream": stream,
            "response_format": "pcm",
        }

        try:
            session = await self._get_session()
            await self.start_tts_usage_metrics(text)

            async with session.post(
                f"{self._base_url}/v1/tts",
                json=payload,
                headers=self._headers(),
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    yield ErrorFrame(error=f"GPU TTS error ({response.status}): {error_text}")
                    return

                if not stream:
                    data = await response.json()
                    import base64

                    pcm = base64.b64decode(data["audio_base64"])
                    server_rate = int(data.get("sample_rate", self.sample_rate))
                    await self.stop_ttfb_metrics()
                    if server_rate != self.sample_rate:
                        from pipecat.audio.utils import create_stream_resampler

                        if not hasattr(self, "_resampler"):
                            self._resampler = create_stream_resampler()
                        pcm = await self._resampler.resample(pcm, server_rate, self.sample_rate)
                    yield TTSAudioRawFrame(
                        audio=pcm,
                        sample_rate=self.sample_rate,
                        num_channels=1,
                        context_id=context_id,
                    )
                    return

                server_rate = int(response.headers.get("X-Sample-Rate", str(self.sample_rate)))
                first_chunk = True

                async for chunk in response.content.iter_chunked(8192):
                    if not chunk:
                        continue
                    if first_chunk:
                        await self.stop_ttfb_metrics()
                        first_chunk = False

                    audio = chunk
                    if server_rate != self.sample_rate:
                        from pipecat.audio.utils import create_stream_resampler

                        if not hasattr(self, "_resampler"):
                            self._resampler = create_stream_resampler()
                        audio = await self._resampler.resample(
                            audio, server_rate, self.sample_rate
                        )

                    yield TTSAudioRawFrame(
                        audio=audio,
                        sample_rate=self.sample_rate,
                        num_channels=1,
                        context_id=context_id,
                    )
        except Exception as exc:
            yield ErrorFrame(error=f"GPU TTS request failed: {exc}")
        finally:
            await self.stop_ttfb_metrics()

    async def cleanup(self):
        await super().cleanup()
        if self._owns_session and self._session:
            await self._session.close()
            self._session = None
