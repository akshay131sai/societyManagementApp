"""Health endpoints.

Unauthenticated, excluded from rate limiting, and deliberately **never** touch a
tenant database — a readiness probe must not open a connection to every society.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.core.firebase import get_token_verifier
from app.database.central import get_central_sessionmaker
from app.database.manager import get_tenant_manager
from app.realtime.hub import get_hub
from app.schemas.common import Envelope, ok
from app.workers.scheduler import scheduler_status

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=Envelope[dict], summary="Liveness")
async def liveness() -> dict[str, Any]:
    settings = get_settings()
    return ok(
        {
            "status": "ok",
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT.value,
        }
    )


@router.get("/ready", response_model=Envelope[dict], summary="Readiness")
async def readiness() -> dict[str, Any]:
    settings = get_settings()
    central_status = "ok"
    passed = True
    try:
        factory = get_central_sessionmaker()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - infrastructure failure
        central_status = f"error: {type(exc).__name__}"
        passed = False

    return ok(
        {
            "status": "ready" if passed else "degraded",
            "central_database": central_status,
            "auth_provider": get_token_verifier().name,
            "tenant_engines_cached": get_tenant_manager().cached_count,
            "checks_passed": passed,
        }
    )


@router.get("/info", response_model=Envelope[dict], summary="Build info")
async def info() -> dict[str, Any]:
    settings = get_settings()
    return ok(
        {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT.value,
            "api_prefix": settings.API_V1_PREFIX,
            "auth_provider": settings.AUTH_PROVIDER.value,
            "locale": settings.DEFAULT_LOCALE,
            "currency": settings.DEFAULT_CURRENCY,
            "timezone": settings.DEFAULT_TIMEZONE,
            # Which sweeps this process is responsible for, and how many live
            # sockets it is holding. Both are per-worker facts, which is
            # exactly what an operator debugging one process needs.
            "scheduler": scheduler_status(),
            "realtime_connections": get_hub().connection_count(),
        }
    )
