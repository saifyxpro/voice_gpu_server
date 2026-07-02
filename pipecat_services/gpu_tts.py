"""HTTP TTS client for voice-gpu-server (Chatterbox Turbo)."""

from __future__ import annotations

import asyncio
import base64
import os
import re
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

import aiohttp
import numpy as np
from loguru import logger

from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.tracing.service_decorators import traced_tts

from pipecat_services.singlish_tts import is_skippable_tts_line, prepare_text_for_tts

# Voice calls: stream PCM only (no batch fallback). Retries are quick reconnects.
_MAX_TTS_ATTEMPTS = 2
_BACKOFF_BASE_S = 0.35
# Pipecat default is 3s; remote GPU/ngrok can gap longer between HTTP stream chunks.
_DEFAULT_STOP_FRAME_TIMEOUT_S = 15.0
# Refresh Pipecat audio-context keepalive if no chunk arrives within this window.
_STREAM_READ_TIMEOUT_S = 8.0
_PEAK_TARGET = 30_000  # int16 — attenuate hot chunks only (no pumping)


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


def _attenuate_peak_pcm(pcm: bytes, peak_target: int = _PEAK_TARGET) -> bytes:
    """Limit loud PCM peaks without boosting quiet sections (avoids chunk-to-chunk pumping)."""
    if not pcm:
        return pcm
    arr = np.frombuffer(pcm, dtype=np.int16)
    if arr.size == 0:
        return pcm
    peak = int(np.max(np.abs(arr)))
    if peak <= peak_target:
        return pcm
    scaled = (arr.astype(np.float32) * (peak_target / peak)).astype(np.int16)
    return scaled.tobytes()


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
        stream_only: Optional[bool] = None,
        stop_frame_timeout_s: Optional[float] = None,
        stream_read_timeout_s: float = _STREAM_READ_TIMEOUT_S,
        **kwargs,
    ):
        default_settings = self.Settings(
            model=None,
            voice=voice_id,
            language=Language.EN,
        )
        if settings is not None:
            default_settings.apply_update(settings)

        transforms = list(kwargs.pop("text_transforms", []) or [])
        transforms.insert(0, ("*", self._transform_tts_text))

        if stop_frame_timeout_s is None:
            stop_frame_timeout_s = float(
                os.getenv("TTS_STOP_FRAME_TIMEOUT_S", str(_DEFAULT_STOP_FRAME_TIMEOUT_S))
            )

        super().__init__(
            sample_rate=sample_rate,
            push_start_frame=True,
            push_stop_frames=True,
            stop_frame_timeout_s=stop_frame_timeout_s,
            reuse_context_id_within_turn=True,
            settings=default_settings,
            text_transforms=transforms,
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
        self._init_voice_id = voice_id
        if stream_only is None:
            stream_only = os.getenv("TTS_STREAM_ONLY", "true").lower() in (
                "1",
                "true",
                "yes",
            )
        self._stream_only = stream_only
        self._stream_read_timeout_s = stream_read_timeout_s
        self._pending_tag_prefix = ""

    async def _transform_tts_text(self, text: str, aggregation_type) -> str:
        """Pipecat hook — filter junk and prepend tags that arrived on their own line."""
        if is_skippable_tts_line(text):
            tag = text.strip()
            if tag.startswith("[") and tag.endswith("]"):
                self._pending_tag_prefix = f"{self._pending_tag_prefix} {tag}".strip()
            return ""
        cleaned = prepare_text_for_tts(text)
        if not cleaned:
            return ""
        if self._pending_tag_prefix:
            cleaned = f"{self._pending_tag_prefix} {cleaned}"
            self._pending_tag_prefix = ""
        return cleaned

    async def on_turn_context_created(self, context_id: str):
        self._pending_tag_prefix = ""
        await super().on_turn_context_created(context_id)

    def _resolved_voice_id(self) -> str:
        return (
            self._settings.voice
            or self._init_voice_id
            or os.getenv("DEFAULT_VOICE_ID", "kelvin")
        )

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

    def _stream_modes(self) -> tuple[bool, ...]:
        return (True,) if self._stream_only else (True, False)

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        """Stream PCM audio from the GPU TTS server (streaming-only for voice calls)."""
        text = prepare_text_for_tts(text)
        if not text:
            logger.debug(f"{self}: skipping empty/filtered TTS line")
            return
        logger.debug(f"{self}: Generating TTS (stream) [{text}]")

        await self.start_tts_usage_metrics(text)
        got_audio = False
        last_error: Optional[ErrorFrame] = None

        for attempt in range(1, self._max_attempts + 1):
            attempt_error: Optional[ErrorFrame] = None
            attempt_audio = False
            stream_complete = False

            async for frame in self._run_tts_request(text, context_id, stream=True):
                if isinstance(frame, ErrorFrame):
                    attempt_error = frame
                    break
                if frame is None:
                    stream_complete = True
                    break
                if isinstance(frame, TTSAudioRawFrame):
                    attempt_audio = True
                    got_audio = True
                yield frame

            if attempt_audio and stream_complete and not attempt_error:
                return

            if attempt_audio:
                # Already yielded partial audio — retrying would duplicate speech.
                if not stream_complete or attempt_error:
                    err = attempt_error.error if attempt_error else "stream ended early"
                    logger.error(
                        f"{self}: incomplete TTS for [{text[:60]}...] — "
                        f"{_short_error(err)}"
                    )
                return

            last_error = attempt_error or ErrorFrame(error="GPU TTS stream returned no audio")

            if attempt < self._max_attempts:
                delay = self._backoff_base_s * (2 ** (attempt - 1))
                logger.warning(
                    f"{self}: stream attempt {attempt}/{self._max_attempts} failed — "
                    f"{_short_error(last_error.error)}; retrying in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
                continue

            logger.error(
                f"{self}: stream failed after {self._max_attempts} attempts — "
                f"{_short_error(last_error.error)}"
            )
            yield last_error
            return

        if not got_audio:
            logger.error(f"{self}: TTS produced no audio for [{text}]")
            yield last_error or ErrorFrame(error="GPU TTS stream produced no audio")

    async def _run_tts_request(
        self, text: str, context_id: str, *, stream: bool
    ) -> AsyncGenerator[Frame, None]:
        payload = {
            "text": text,
            "voice_id": self._resolved_voice_id(),
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

                        if not hasattr(self, "_batch_resampler"):
                            self._batch_resampler = create_stream_resampler()
                        pcm = await self._batch_resampler.resample(
                            pcm, server_rate, self.sample_rate
                        )
                    pcm = _attenuate_peak_pcm(pcm)
                    yield TTSAudioRawFrame(
                        audio=pcm,
                        sample_rate=self.sample_rate,
                        num_channels=1,
                        context_id=context_id,
                    )
                    return

                server_rate = int(response.headers.get("X-Sample-Rate", str(self.sample_rate)))
                first_chunk = True

                async for audio in self._iter_stream_pcm(
                    response, context_id=context_id, server_rate=server_rate
                ):
                    if first_chunk:
                        await self.stop_ttfb_metrics()
                        first_chunk = False

                    yield TTSAudioRawFrame(
                        audio=audio,
                        sample_rate=self.sample_rate,
                        num_channels=1,
                        context_id=context_id,
                    )

                if first_chunk:
                    yield ErrorFrame(error="GPU TTS stream returned no audio chunks")
                    return

                yield None
        except Exception as exc:
            yield ErrorFrame(error=f"GPU TTS request failed: {exc}")
        finally:
            await self.stop_ttfb_metrics()

    async def _iter_stream_pcm(
        self,
        response: aiohttp.ClientResponse,
        *,
        context_id: str,
        server_rate: int,
    ) -> AsyncGenerator[bytes, None]:
        """Read PCM chunks with keepalive refreshes during slow GPU/ngrok gaps."""
        while True:
            try:
                chunk = await asyncio.wait_for(
                    response.content.read(8192),
                    timeout=self._stream_read_timeout_s,
                )
            except asyncio.TimeoutError:
                self._refresh_audio_context(context_id)
                continue

            if not chunk:
                break

            audio = chunk
            if server_rate != self.sample_rate:
                from pipecat.audio.utils import create_stream_resampler

                if not hasattr(self, "_stream_resampler"):
                    self._stream_resampler = create_stream_resampler()
                audio = await self._stream_resampler.resample(
                    audio, server_rate, self.sample_rate
                )

            yield _attenuate_peak_pcm(audio)

    async def cleanup(self):
        await super().cleanup()
        if self._owns_session and self._session:
            await self._session.close()
            self._session = None
