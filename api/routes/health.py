"""Health & readiness endpoints (unauthenticated)."""

from __future__ import annotations

from fastapi import APIRouter

from config.settings import settings
from data.db import ping as db_ping
from data.redis_client import ping as redis_ping

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    """Liveness — cheap check that the process is up."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
        "version": "0.1.0",
    }


@router.get("/health/deep")
async def health_deep() -> dict[str, object]:
    """Readiness — verifies downstream dependencies."""
    db_ok = await db_ping()
    redis_ok = await redis_ping()
    healthy = db_ok and redis_ok
    return {
        "status": "ok" if healthy else "degraded",
        "database": "up" if db_ok else "down",
        "redis": "up" if redis_ok else "down",
    }
