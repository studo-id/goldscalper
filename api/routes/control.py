"""Authenticated runtime control endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth import require_token
from api.deps import RuntimeDep
from config.logging import get_logger

log = get_logger("api.control")

router = APIRouter(
    prefix="/api", tags=["control"], dependencies=[Depends(require_token)]
)


class ManualOrder(BaseModel):
    side: str = Field(pattern="^(BUY|SELL|buy|sell)$")
    size: float = Field(gt=0, le=50)
    sl: float | None = None
    tp: float | None = None


@router.get("/status")
async def status_endpoint(runtime: RuntimeDep) -> dict[str, Any]:
    return runtime.snapshot()


@router.get("/control/config")
async def config_endpoint(runtime: RuntimeDep) -> dict[str, Any]:
    from config.settings import settings

    return {
        "risk": {
            "risk_per_trade_pct": settings.risk_per_trade_pct,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
            "max_weekly_loss_pct": settings.max_weekly_loss_pct,
            "max_consecutive_losses": settings.max_consecutive_losses,
            "max_spread_points": settings.max_spread_points,
            "max_open_positions": settings.max_open_positions,
            "default_rr": settings.default_rr,
            "atr_sl_multiplier": settings.atr_sl_multiplier,
            "max_hold_seconds": settings.max_hold_seconds,
            "cycle_interval_ms": settings.cycle_interval_ms,
            "min_lot": settings.min_lot,
            "max_lot": settings.max_lot,
        },
        "system": {
            "app_name": settings.app_name,
            "environment": settings.environment,
            "symbol": settings.mt5_symbol,
            "server": settings.mt5_server,
            "magic": settings.mt5_magic,
            "db_host": settings.db_host,
            "db_port": settings.db_port,
            "db_name": settings.db_name,
            "redis_host": settings.redis_host,
            "redis_port": settings.redis_port,
            "telegram_enabled": settings.telegram_enabled,
            "agents_count": runtime.registry.size if hasattr(runtime, "registry") else 37,
            "algo_trading": getattr(runtime.client, "trade_allowed", True) and not runtime.paused,
        },
    }


@router.post("/control/pause")
async def pause_endpoint(runtime: RuntimeDep) -> dict[str, Any]:
    runtime.paused = True
    log.info("runtime paused via API")
    return {"paused": True}


@router.post("/control/resume")
async def resume_endpoint(runtime: RuntimeDep) -> dict[str, Any]:
    runtime.paused = False
    log.info("runtime resumed via API")
    return {"paused": False}


@router.post("/control/panic")
async def panic_endpoint(runtime: RuntimeDep) -> dict[str, Any]:
    closed = await runtime.panic_close()
    log.warning("panic close via API: %d positions", closed)
    return {"closed": closed}


@router.post("/control/manual")
async def manual_endpoint(payload: ManualOrder, runtime: RuntimeDep) -> dict[str, Any]:
    result = await runtime.manual_order(payload.side, payload.size, payload.sl, payload.tp)
    log.info("manual order via API: %s", result)
    return result


@router.post("/control/close")
async def close_endpoint(runtime: RuntimeDep, ticket: int = Query(...)) -> dict[str, Any]:
    ok = await runtime.close_single_position(ticket)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Failed to close position #{ticket}")
    log.info("position closed via API: ticket=%d", ticket)
    return {"ticket": ticket, "closed": True}



__all__ = ["router"]
