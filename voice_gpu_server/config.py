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
            eager_load_models=os.getenv("EAGER_LOAD_MODELS", "false").lower() == "true",
            tts_model=os.getenv("TTS_MODEL", "ResembleAI/chatterbox-turbo"),
            stt_model=os.getenv("STT_MODEL", "nvidia/canary-qwen-2.5b"),
            default_voice_id=os.getenv("DEFAULT_VOICE_ID", "default"),
            voices_dir=voices_dir,
            stt_sample_rate=int(os.getenv("STT_SAMPLE_RATE", "16000")),
            public_base_url=os.getenv("VOICE_GPU_BASE_URL") or None,
        )


settings = Settings.from_env()
