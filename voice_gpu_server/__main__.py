"""CLI entry point."""

from __future__ import annotations

import uvicorn
from loguru import logger

from voice_gpu_server.config import settings


def main() -> None:
    logger.info(
        "Starting voice-gpu-server on {}:{} (eager_load={})",
        settings.host,
        settings.port,
        settings.eager_load_models,
    )
    uvicorn.run(
        "voice_gpu_server.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
