"""Unit tests for VoiceGpuTTSService retry and fallback logic."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientTimeout
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame

from pipecat_services.gpu_tts import VoiceGpuTTSService, _short_error


def test_short_error_ngrok_html():
    html = (
        'GPU TTS error (503): <!DOCTYPE html><html><body>ERR_NGROK_3004 '
        "upstream connect error</body></html>"
    )
    assert _short_error(html) == "gateway error (ERR_NGROK_3004)"


def test_short_error_plain():
    assert _short_error("connection reset") == "connection reset"


@pytest.mark.asyncio
async def test_run_tts_falls_back_to_batch_after_stream_failure():
    """Streaming 503 then batch success should yield audio."""
    pcm = b"\x00\x01" * 120
    encoded = __import__("base64").b64encode(pcm).decode("ascii")
    stream_calls = 0
    batch_calls = 0

    async def tts_handler(request: web.Request) -> web.StreamResponse:
        nonlocal stream_calls, batch_calls
        body = await request.json()
        if body.get("stream"):
            stream_calls += 1
            return web.Response(status=503, text="upstream unavailable")
        batch_calls += 1
        return web.json_response(
            {"audio_base64": encoded, "sample_rate": 24000, "format": "pcm"}
        )

    app = web.Application()
    app.router.add_post("/v1/tts", tts_handler)
    server = TestServer(app)
    client = TestClient(server, timeout=ClientTimeout(total=30))

    await client.start_server()
    try:
        tts = VoiceGpuTTSService(
            base_url=str(client.make_url("")),
            max_attempts=1,
            backoff_base_s=0.01,
            aiohttp_session=client.session,
        )
        frames = []
        async for frame in tts.run_tts("Hello there", "ctx-1"):
            frames.append(frame)

        audio = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
        errors = [f for f in frames if isinstance(f, ErrorFrame)]
        assert stream_calls == 1
        assert batch_calls == 1
        assert len(audio) == 1
        assert audio[0].audio == pcm
        assert not errors
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_run_tts_retries_batch_with_backoff():
    """Batch mode should retry before yielding a final error."""
    pcm = b"\x00\x01" * 80
    encoded = __import__("base64").b64encode(pcm).decode("ascii")
    batch_calls = 0

    async def tts_handler(request: web.Request) -> web.StreamResponse:
        nonlocal batch_calls
        body = await request.json()
        if body.get("stream"):
            return web.Response(status=503, text="fail")
        batch_calls += 1
        if batch_calls < 2:
            return web.Response(status=503, text="still failing")
        return web.json_response(
            {"audio_base64": encoded, "sample_rate": 24000, "format": "pcm"}
        )

    app = web.Application()
    app.router.add_post("/v1/tts", tts_handler)
    server = TestServer(app)
    client = TestClient(server, timeout=ClientTimeout(total=30))

    await client.start_server()
    try:
        tts = VoiceGpuTTSService(
            base_url=str(client.make_url("")),
            max_attempts=3,
            backoff_base_s=0.01,
            aiohttp_session=client.session,
        )
        frames = []
        async for frame in tts.run_tts("Second sentence", "ctx-2"):
            frames.append(frame)

        audio = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
        assert batch_calls == 2
        assert len(audio) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_run_tts_yields_error_when_all_attempts_fail():
    async def tts_handler(request: web.Request) -> web.StreamResponse:
        return web.Response(status=503, text="ERR_NGROK_3004")

    app = web.Application()
    app.router.add_post("/v1/tts", tts_handler)
    server = TestServer(app)
    client = TestClient(server, timeout=ClientTimeout(total=30))

    await client.start_server()
    try:
        tts = VoiceGpuTTSService(
            base_url=str(client.make_url("")),
            max_attempts=2,
            backoff_base_s=0.01,
            aiohttp_session=client.session,
        )
        frames = []
        async for frame in tts.run_tts("No audio", "ctx-3"):
            frames.append(frame)

        audio = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
        errors = [f for f in frames if isinstance(f, ErrorFrame)]
        assert not audio
        assert len(errors) == 1
        assert "503" in errors[0].error
    finally:
        await client.close()
