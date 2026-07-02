"""Pydantic request/response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    tts_loaded: bool
    stt_loaded: bool
    tts_device: str
    stt_device: str
    tts_sample_rate: int | None = None
    stt_sample_rate: int
    public_base_url: str | None = None


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice_id: str | None = None
    stream: bool = True
    response_format: Literal["pcm", "wav"] = "pcm"


class TTSResponse(BaseModel):
    text: str
    voice_id: str
    sample_rate: int
    audio_base64: str | None = None
    format: str


class STTResponse(BaseModel):
    text: str
    language: str = "en"


class VoiceInfo(BaseModel):
    voice_id: str
    path: str


class VoicesListResponse(BaseModel):
    voices: list[VoiceInfo]
    default_voice_id: str
