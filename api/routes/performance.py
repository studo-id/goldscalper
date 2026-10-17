"""Performance endpoints (aggregate stats + equity curve with date range filtering)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from api.auth import require_token
from api.deps import RuntimeDep

router = APIRouter(
    prefix="/api", tags=["performance"], dependencies=[Depends(require_token)]
)


@router.get("/performance")
async def performance(
    runtime: RuntimeDep,
    period: str = Query(default="all"),
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=10, le=10000),
) -> dict[str, Any]:
    repo = getattr(runtime.order_manager, "trade_repo", None)
    if repo is None:
        return {"stats": {}, "equity_curve": [], "source": "live", "period": period}

    WIB = timezone(timedelta(hours=7))
    now_utc = datetime.now(timezone.utc)
    now_wib = now_utc.astimezone(WIB)
    since_dt: datetime | None = None
    until_dt: datetime | None = None

    period_lower = (period or "all").lower()
    if period_lower == "today":
        # Midnight WIB today (00:00:00 WIB = 17:00:00 UTC previous day)
        since_dt = datetime(now_wib.year, now_wib.month, now_wib.day, tzinfo=WIB)
        until_dt = now_utc
    elif period_lower == "yesterday":
        today_start_wib = datetime(now_wib.year, now_wib.month, now_wib.day, tzinfo=WIB)
        since_dt = today_start_wib - timedelta(days=1)
        until_dt = today_start_wib
    elif period_lower == "week":
        since_dt = now_utc - timedelta(days=7)
        until_dt = now_utc
    elif period_lower == "month":
        since_dt = now_utc - timedelta(days=30)
        until_dt = now_utc
    elif period_lower == "custom":
        if since:
            try:
                dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                since_dt = dt if dt.tzinfo else dt.replace(tzinfo=WIB)
            except Exception:
                pass
        if until:
            try:
                dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
                until_dt = dt if dt.tzinfo else dt.replace(tzinfo=WIB)
            except Exception:
                pass

    base_balance = 10_000.0
    if since_dt is not None and hasattr(repo, "prior_pnl"):
        prior = await repo.prior_pnl(until=since_dt)
        balance = base_balance + prior
    else:
        balance = base_balance

    stats = await repo.aggregate(since=since_dt, until=until_dt)
    curve_rows = await repo.equity_curve(limit=limit, since=since_dt, until=until_dt)

    if not curve_rows:
        stats["total"] = stats.pop("trades", 0)
        stats["final_equity"] = round(balance, 2)
        stats["max_drawdown"] = 0.0
        t_start = since_dt.isoformat() if since_dt else now_utc.isoformat()
        return {
            "stats": stats,
            "equity_curve": [
                {"t": t_start, "pnl": 0.0, "equity": round(balance, 2)},
                {"t": now_utc.isoformat(), "pnl": 0.0, "equity": round(balance, 2)},
            ],
            "source": "db",
            "period": period_lower,
            "since": since_dt.isoformat() if since_dt else None,
            "until": until_dt.isoformat() if until_dt else None,
            "base_equity": round(balance, 2),
            "trades": [],
            "total_trades": 0,
        }

    curve: list[dict[str, Any]] = []
    cumulative = 0.0
    peak = balance
    max_dd = 0.0
    for row in curve_rows:
        cumulative += float(row.get("pnl") or 0.0)
        equity = balance + cumulative
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
        curve.append(
            {
                "t": row.get("closed_at"),
                "pnl": float(row.get("pnl") or 0.0),
                "equity": round(equity, 2),
            }
        )

    stats["total"] = stats.pop("trades", 0)
    stats["final_equity"] = round(balance + cumulative, 2)
    stats["max_drawdown"] = round(max_dd, 4)

    recent_trades = await repo.list_recent(limit=50, offset=0, since=since_dt, until=until_dt)
    total_trades_count = await repo.count_trades(status="CLOSED", since=since_dt, until=until_dt)

    return {
        "stats": stats,
        "equity_curve": curve,
        "source": "db",
        "period": period_lower,
        "since": since_dt.isoformat() if since_dt else None,
        "until": until_dt.isoformat() if until_dt else None,
        "base_equity": round(balance, 2),
        "trades": recent_trades,
        "total_trades": total_trades_count,
    }


__all__ = ["router"]
