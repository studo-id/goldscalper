"""BizDev analytics endpoint: daily rebate extraction, fee friction, and net yield."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends

from api.auth import require_token
from api.deps import RuntimeDep
from config.settings import settings

router = APIRouter(
    prefix="/api", tags=["bizdev"], dependencies=[Depends(require_token)]
)


@router.get("/bizdev/daily")
async def bizdev_daily(runtime: RuntimeDep) -> dict[str, Any]:
    WIB = timezone(timedelta(hours=7))
    now_utc = datetime.now(timezone.utc)
    now_wib = now_utc.astimezone(WIB)
    today_start = datetime(now_wib.year, now_wib.month, now_wib.day, tzinfo=WIB)

    repo = getattr(runtime.order_manager, "trade_repo", None)
    if repo is not None:
        try:
            stats = await repo.aggregate(since=today_start, until=now_utc)
            total_lots = float(stats.get("total_lots", 0.0) or 0.0)
            gross_profit = float(stats.get("gross_profit", 0.0) or 0.0)
            gross_loss = float(stats.get("gross_loss", 0.0) or 0.0)
            total_pnl = float(stats.get("total_pnl", 0.0) or 0.0)
            total_trades = int(stats.get("trades", 0) or 0)
            avg_win = float(stats.get("avg_win", 0.0) or 0.0)
            avg_loss = float(stats.get("avg_loss", 0.0) or 0.0)
        except Exception:
            total_lots = runtime._daily_lots_traded
            gross_profit = runtime._daily_gross_profit
            gross_loss = runtime._daily_gross_loss
            total_pnl = runtime._daily_realized_pnl
            total_trades = runtime.orders_placed
            avg_win = 0.0
            avg_loss = 0.0
    else:
        total_lots = runtime._daily_lots_traded
        gross_profit = runtime._daily_gross_profit
        gross_loss = runtime._daily_gross_loss
        total_pnl = runtime._daily_realized_pnl
        total_trades = runtime.orders_placed
        avg_win = 0.0
        avg_loss = 0.0

    rebate_rate = settings.rebate_per_lot_usd
    est_rebate = round(total_lots * rebate_rate, 2)
    friction_cost = round(total_lots * settings.commission_per_lot, 2)
    friction_ratio = round((friction_cost / gross_profit) * 100.0, 1) if gross_profit > 0 else 0.0
    net_yield = round(total_pnl + est_rebate - friction_cost, 2)

    return {
        "date": today_start.strftime("%Y-%m-%d"),
        "total_trades": total_trades,
        "total_lots": round(total_lots, 2),
        "rebate_rate_usd": rebate_rate,
        "estimated_rebate_usd": est_rebate,
        "gross_profit_usd": round(gross_profit, 2),
        "gross_loss_usd": round(gross_loss, 2),
        "trading_pnl_usd": round(total_pnl, 2),
        "friction_cost_usd": friction_cost,
        "friction_ratio_pct": friction_ratio,
        "max_friction_ratio_pct": settings.max_friction_ratio_pct,
        "net_yield_usd": net_yield,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "juggler": {
            "hard_clamp_usd": settings.hard_loss_clamp_usd,
            "daily_target_pct": settings.daily_profit_target_pct,
            "daily_loss_limit_pct": settings.daily_loss_limit_pct,
            "lot_sizing_mode": settings.lot_sizing_mode,
        },
    }
