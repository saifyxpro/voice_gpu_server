"""Application configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment."""

    host: str
    port: int
    api_key: str | None
    tts_device: str
    stt_device: str
    eager_load_models: bool
    tts_model: str
    stt_model: str
    default_voice_id: str
    voices_dir: Path
    stt_sample_rate: int
    public_base_url: str | None
    tts_temperature: float
    tts_top_p: float
    tts_top_k: int
    tts_repetition_penalty: float
    tts_exaggeration: float
    tts_norm_loudness: bool
    tts_stream_chunk_tokens: int
    tts_stream_crossfade_ms: float
    tts_max_gen_len: int
    tts_n_cfm_timesteps: int

    @classmethod
    def from_env(cls) -> Settings:
        voices_dir = Path(os.getenv("VOICES_DIR", str(_ROOT / "voices"))).expanduser()
        if not voices_dir.is_absolute():
            voices_dir = (_ROOT / voices_dir).resolve()

        api_key = os.getenv("VOICE_GPU_API_KEY") or None
        if api_key == "":
            api_key = None

        return cls(
            host=os.getenv("VOICE_GPU_HOST", "0.0.0.0"),
            port=int(os.getenv("VOICE_GPU_PORT", "8765")),
            api_key=api_key,
            tts_device=os.getenv("TTS_DEVICE", "cuda"),
            stt_device=os.getenv("STT_DEVICE", "cuda"),
            eager_load_models=os.getenv("EAGER_LOAD_MODELS", "true").lower() == "true",
            tts_model=os.getenv("TTS_MODEL", "ResembleAI/chatterbox-turbo"),
            stt_model=os.getenv("STT_MODEL", "nvidia/canary-qwen-2.5b"),
            default_voice_id=os.getenv("DEFAULT_VOICE_ID", "default"),
            voices_dir=voices_dir,
            stt_sample_rate=int(os.getenv("STT_SAMPLE_RATE", "16000")),
            public_base_url=os.getenv("VOICE_GPU_BASE_URL") or None,
            tts_temperature=float(os.getenv("TTS_TEMPERATURE", "0.8")),
            tts_top_p=float(os.getenv("TTS_TOP_P", "0.95")),
            tts_top_k=int(os.getenv("TTS_TOP_K", "1000")),
            tts_repetition_penalty=float(os.getenv("TTS_REPETITION_PENALTY", "1.2")),
            tts_exaggeration=float(os.getenv("TTS_EXAGGERATION", "0.5")),
            tts_norm_loudness=os.getenv("TTS_NORM_LOUDNESS", "true").lower() == "true",
            tts_stream_chunk_tokens=int(os.getenv("TTS_STREAM_CHUNK_TOKENS", "16")),
            tts_stream_crossfade_ms=float(os.getenv("TTS_STREAM_CROSSFADE_MS", "12.0")),
            tts_max_gen_len=int(os.getenv("TTS_MAX_GEN_LEN", "1000")),
            tts_n_cfm_timesteps=int(os.getenv("TTS_N_CFM_TIMESTEPS", "2")),
        )


settings = Settings.from_env()
