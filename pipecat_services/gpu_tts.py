"""HTTP TTS client for voice-gpu-server (Chatterbox Turbo)."""

from __future__ import annotations

import asyncio
import base64
import os
import re
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

import aiohttp
from loguru import logger

from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.tracing.service_decorators import traced_tts

from pipecat_services.singlish_tts import normalize_singlish_for_tts

# Retries per mode (streaming, then batch fallback).
_MAX_TTS_ATTEMPTS = 3
_BACKOFF_BASE_S = 0.75


def _short_error(error: str, max_len: int = 240) -> str:
    """Collapse ngrok/HTML gateway errors into a short log line."""
    if "<html" in error.lower():
        ngrok_code = re.search(r"ERR_NGROK_\d+", error)
        if ngrok_code:
            return f"gateway error ({ngrok_code.group(0)})"
        status = re.search(r"\((\d{3})\)", error)
        if status:
            return f"gateway error (HTTP {status.group(1)})"
        return "gateway error (HTML response)"
    return error if len(error) <= max_len else f"{error[: max_len - 3]}..."


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
        max_attempts: int = _MAX_TTS_ATTEMPTS,
        backoff_base_s: float = _BACKOFF_BASE_S,
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
        self._max_attempts = max(1, max_attempts)
        self._backoff_base_s = backoff_base_s

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
        text = normalize_singlish_for_tts(text)
        if not text:
            logger.debug(f"{self}: skipping empty/tag-only TTS line")
            return
        logger.debug(f"{self}: Generating TTS [{text}]")

        await self.start_tts_usage_metrics(text)
        got_audio = False
        last_error: Optional[ErrorFrame] = None

        for stream in (True, False):
            mode = "streaming" if stream else "batch"
            for attempt in range(1, self._max_attempts + 1):
                attempt_error: Optional[ErrorFrame] = None
                attempt_audio = False

                async for frame in self._run_tts_request(text, context_id, stream=stream):
                    if isinstance(frame, ErrorFrame):
                        attempt_error = frame
                        break
                    if isinstance(frame, TTSAudioRawFrame):
                        attempt_audio = True
                        got_audio = True
                    yield frame

                if attempt_audio:
                    return

                last_error = attempt_error or ErrorFrame(
                    error=f"GPU TTS {mode} returned no audio"
                )

                if attempt < self._max_attempts:
                    delay = self._backoff_base_s * (2 ** (attempt - 1))
                    logger.warning(
                        f"{self}: {mode} attempt {attempt}/{self._max_attempts} failed — "
                        f"{_short_error(last_error.error)}; retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    continue

                if stream:
                    logger.warning(
                        f"{self}: {mode} failed after {self._max_attempts} attempts — "
                        f"{_short_error(last_error.error)}; falling back to batch"
                    )
                    break

                logger.error(
                    f"{self}: TTS produced no audio after {self._max_attempts} batch attempts — "
                    f"{_short_error(last_error.error)}"
                )
                yield last_error
                return

        if not got_audio:
            logger.error(f"{self}: TTS produced no audio for [{text}]")
            yield last_error or ErrorFrame(error="GPU TTS produced no audio after retries")

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
                    audio_b64 = data.get("audio_base64")
                    if not audio_b64:
                        yield ErrorFrame(error="GPU TTS batch response missing audio_base64")
                        return

                    pcm = base64.b64decode(audio_b64)
                    if not pcm:
                        yield ErrorFrame(error="GPU TTS batch response contained empty audio")
                        return

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
