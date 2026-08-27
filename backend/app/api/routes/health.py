"""Health and capability endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...ai.client import AIService
from ...config import Settings, get_settings
from ..deps import get_ai_service

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/config")
async def config(
    settings: Settings = Depends(get_settings),
    ai: AIService = Depends(get_ai_service),
) -> dict:
    """What the frontend needs to know about this deployment.

    Deliberately exposes capability flags only — never the API key, and never
    the provider's base URL.
    """
    return {
        "app_name": settings.app_name,
        "ai_enabled": ai.is_enabled,
        "ai_provider": ai.provider_name,
        "max_upload_mb": round(settings.max_upload_bytes / 1_048_576),
        "allowed_extensions": list(settings.allowed_extensions),
        "max_rows_analyzed": settings.max_rows_analyzed,
    }
