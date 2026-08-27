"""Health and capability endpoints."""

from __future__ import annotations

from urllib.parse import urlparse

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

    Exposes capability flags and *safe* storage diagnostics only — never the
    service key. `supabase_host` (hostname, not a secret) lets you confirm from
    the browser that SUPABASE_URL points at your Supabase project rather than
    the frontend/Vercel/Render URL — the cause of the upload 404.
    """
    supabase_host = None
    if settings.storage_backend.lower() == "supabase" and settings.supabase_url:
        supabase_host = urlparse(settings.supabase_url).hostname

    return {
        "app_name": settings.app_name,
        "ai_enabled": ai.is_enabled,
        "ai_provider": ai.provider_name,
        "max_upload_mb": round(settings.max_upload_bytes / 1_048_576),
        "allowed_extensions": list(settings.allowed_extensions),
        "max_rows_analyzed": settings.max_rows_analyzed,
        "storage_backend": settings.storage_backend,
        "supabase_host": supabase_host,
        "supabase_configured": settings.supabase_configured,
    }
