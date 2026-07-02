"""API key authentication."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from voice_gpu_server.config import settings


async def verify_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Require API key when VOICE_GPU_API_KEY is configured."""
    if not settings.api_key:
        return

    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_api_key:
        token = x_api_key

    if token != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
