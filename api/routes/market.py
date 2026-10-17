"""Market data endpoints for chart rendering and historical candle lookup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import require_token
from api.deps import RuntimeDep
from core.market_data import TIMEFRAMES, Candle, tf_seconds

router = APIRouter(
    prefix="/api", tags=["market"], dependencies=[Depends(require_token)]
)


from config.logging import get_logger

log = get_logger("api.routes.market")


def _to_bar(c: Candle) -> dict[str, Any]:
    t = c.time.replace(tzinfo=UTC) if c.time.tzinfo is None else c.time
    return {
        "time": int(t.timestamp()),
        "open": round(c.open, 2),
        "high": round(c.high, 2),
        "low": round(c.low, 2),
        "close": round(c.close, 2),
        "volume": round(c.volume, 2),
    }


@router.get("/candles")
async def get_candles(
    runtime: RuntimeDep,
    tf: str = Query(default="M1", description="Timeframe code (M1, M5, M15, M30, H1, H4, D1)"),
    limit: int = Query(default=500, ge=10, le=2000, description="Number of bars to return"),
    before: int | None = Query(default=None, description="Unix timestamp (seconds) cursor; return bars before this time"),
) -> dict[str, Any]:
    timeframe = tf.upper()
    if timeframe not in TIMEFRAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid timeframe '{tf}'. Supported: {', '.join(TIMEFRAMES)}",
        )

    symbol = runtime.symbol
    secs = tf_seconds(timeframe)

    # 1. If requesting recent bars without cursor, check in-memory cache
    if before is None:
        cached_candles = runtime.cache.latest(symbol, timeframe, limit)
        # If cache can fully satisfy the requested limit, return it immediately
        if cached_candles and len(cached_candles) >= limit:
            bars = [_to_bar(c) for c in cached_candles]
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": bars,
                "count": len(bars),
                "source": "cache",
            }

    # 2. Query MT5 client / broker
    end = datetime.fromtimestamp(before, tz=UTC) if before is not None else datetime.now(UTC)
    multiplier = 2.5 if timeframe in ("D1", "H4", "H1") else 1.8
    lookback_secs = int(secs * limit * multiplier)
    start = end - timedelta(seconds=max(lookback_secs, 3600))

    rates: list[Candle] = []
    try:
        raw_rates = await runtime.client.copy_rates(symbol, timeframe, start, end)
        if raw_rates:
            if before is not None:
                rates = [c for c in raw_rates if int(c.time.timestamp()) < before]
            else:
                rates = raw_rates
    except Exception as exc:
        log.warning("Client copy_rates failed: %s", exc)

    # 3. Fallback to TimescaleDB repository if MT5 returned too few bars
    streamer = getattr(runtime, "streamer", None)
    repo = getattr(streamer, "repo", None) if streamer else None
    if len(rates) < min(10, limit) and repo:
        try:
            db_rows = await repo.fetch_candles(
                symbol, timeframe, limit=limit, before=end if before is not None else None
            )
            if db_rows:
                db_candles = [
                    Candle(
                        symbol=r["symbol"],
                        timeframe=r["timeframe"],
                        time=r["time"] if r["time"].tzinfo else r["time"].replace(tzinfo=UTC),
                        open=float(r["open"]),
                        high=float(r["high"]),
                        low=float(r["low"]),
                        close=float(r["close"]),
                        volume=float(r.get("volume", 0.0) or 0.0),
                        spread_avg=float(r.get("spread_avg", 0.0) or 0.0),
                    )
                    for r in reversed(db_rows)
                ]
                if not rates:
                    rates = db_candles
                else:
                    existing_times = {int(c.time.timestamp()) for c in rates}
                    for c in db_candles:
                        if int(c.time.timestamp()) not in existing_times:
                            rates.append(c)
                    rates.sort(key=lambda c: c.time)
        except Exception as exc:
            log.warning("DB fetch_candles fallback failed: %s", exc)

    # 4. Fallback to cache if still no rates and before is None
    if not rates and before is None:
        rates = runtime.cache.latest(symbol, timeframe, limit) or []

    bars = [_to_bar(c) for c in rates[-limit:]]

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": bars,
        "count": len(bars),
        "source": "client" if rates else "fallback",
    }


__all__ = ["router"]
