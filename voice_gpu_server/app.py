"""FastAPI application exposing TTS/STT endpoints."""

from __future__ import annotations

import base64
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from loguru import logger

from voice_gpu_server import __version__
from voice_gpu_server.audio_utils import chunk_bytes, pcm_to_wav
from voice_gpu_server.auth import verify_api_key
from voice_gpu_server.config import settings
from voice_gpu_server.models import model_manager
from voice_gpu_server.schemas import (
    HealthResponse,
    STTResponse,
    TTSRequest,
    TTSResponse,
    VoiceInfo,
    VoicesListResponse,
)

PCM_MEDIA_TYPE = "audio/pcm"
WAV_MEDIA_TYPE = "audio/wav"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await model_manager.warmup()
    yield


app = FastAPI(
    title="Voice GPU Server",
    version=__version__,
    description="Chatterbox Turbo TTS + Canary Qwen STT for Pipecat voice bots",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check with model load status."""
    return HealthResponse(
        status="ok",
        tts_loaded=model_manager.tts.is_loaded,
        stt_loaded=model_manager.stt.is_loaded,
        tts_device=settings.tts_device,
        stt_device=settings.stt_device,
        tts_sample_rate=model_manager.tts.sample_rate,
        stt_sample_rate=settings.stt_sample_rate,
        public_base_url=settings.public_base_url,
    )


@app.get("/v1/voices", response_model=VoicesListResponse, dependencies=[Depends(verify_api_key)])
async def list_voices() -> VoicesListResponse:
    voices = [
        VoiceInfo(voice_id=vid, path=str(path))
        for vid, path in model_manager.tts.list_voices()
    ]
    return VoicesListResponse(voices=voices, default_voice_id=settings.default_voice_id)


@app.post("/v1/tts", dependencies=[Depends(verify_api_key)])
async def synthesize(request: TTSRequest):
    """Synthesize speech. Returns streaming PCM/WAV or JSON with base64 audio."""
    try:
        voice_id = request.voice_id or settings.default_voice_id
        pcm, sample_rate = await model_manager.tts.synthesize(request.text, voice_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("TTS synthesis failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if request.response_format == "wav":
        payload = pcm_to_wav(pcm, sample_rate)
        media_type = WAV_MEDIA_TYPE
    else:
        payload = pcm
        media_type = PCM_MEDIA_TYPE

    if request.stream:
        return StreamingResponse(
            chunk_bytes(payload),
            media_type=media_type,
            headers={
                "X-Sample-Rate": str(sample_rate),
                "X-Voice-Id": voice_id,
                "X-Audio-Format": request.response_format,
            },
        )

    encoded = base64.b64encode(payload).decode("ascii")
    return TTSResponse(
        text=request.text,
        voice_id=voice_id,
        sample_rate=sample_rate,
        audio_base64=encoded,
        format=request.response_format,
    )


@app.post("/v1/stt", response_model=STTResponse, dependencies=[Depends(verify_api_key)])
async def transcribe(file: UploadFile = File(...)) -> STTResponse:
    """Transcribe uploaded WAV audio (16-bit mono). Resampled to 16 kHz for Canary."""
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty audio file")

    try:
        text = await model_manager.stt.transcribe(audio_bytes)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("STT transcription failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return STTResponse(text=text, language="en")


@app.get("/")
async def root():
    return {
        "service": "voice-gpu-server",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
    }
