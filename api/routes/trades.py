"""Trade & position endpoints (DB-backed, with live fallback)."""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from api.auth import require_token
from api.deps import RuntimeDep

router = APIRouter(
    prefix="/api", tags=["trades"], dependencies=[Depends(require_token)]
)


@router.get("/trades")
async def trades(
    runtime: RuntimeDep,
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
) -> dict[str, Any]:
    repo = getattr(runtime.order_manager, "trade_repo", None)
    live_open = [{"ticket": ticket, **info} for ticket, info in runtime._trades.items()]
    if repo is None:
        return {
            "open": live_open,
            "recent": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
            "has_more": False,
            "source": "live",
        }

    WIB = timezone(timedelta(hours=7))
    since_dt: datetime | None = None
    until_dt: datetime | None = None
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

    recent_rows = await repo.list_recent(limit=limit, offset=offset, status="CLOSED", since=since_dt, until=until_dt)
    total = await repo.count_trades(status="CLOSED", since=since_dt, until=until_dt)
    has_more = (offset + len(recent_rows)) < total
    return {
        "open": live_open,
        "recent": recent_rows,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "currency": getattr(runtime, "_account_currency", "USC" if getattr(runtime, "symbol", "").endswith("c") else "USD"),
        "source": "db",
    }


@router.get("/positions")
async def positions(runtime: RuntimeDep) -> dict[str, Any]:
    live = [{"ticket": ticket, **info} for ticket, info in runtime._trades.items()]
    return {"open_trades": live, "count": len(live)}


__all__ = ["router"]
