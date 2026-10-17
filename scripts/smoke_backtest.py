"""Backtest smoke — replay history through the full agent stack.

Tries to load real OHLCV from TimescaleDB; falls back to synthetic candles from
the mock client when the DB is empty. Prints performance stats and the top
learned patterns.

Run inside the compose network:
    docker compose run --rm bot python scripts/smoke_backtest.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest import BacktestEngine, load_history_from_repo  # noqa: E402
from backtest.metrics import format_stats  # noqa: E402
from core.market_data import TIMEFRAMES  # noqa: E402
from core.mt5_connector import MockMT5Client  # noqa: E402
from data.repositories import MarketDataRepository  # noqa: E402

SYMBOL = "XAUUSD"
END = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)


async def _synthetic(hours: int = 6) -> dict:
    client = MockMT5Client()
    start = END - timedelta(hours=hours)
    history: dict[str, list] = {}
    for tf in TIMEFRAMES:
        for _ in range(3):
            candles = await client.copy_rates(SYMBOL, tf, start, END)
            if candles:
                history[tf] = candles
                break
    return history


async def main() -> None:
    repo = MarketDataRepository()
    history: dict = {}
    try:
        history = await load_history_from_repo(repo, SYMBOL, TIMEFRAMES, limit=3000)
    except Exception as exc:  # noqa: BLE001
        print(f"db load failed ({exc}); using synthetic")

    if not history.get("M1") or len(history["M1"]) < 50:
        print("db empty/short; using synthetic candles")
        history = await _synthetic()

    engine = BacktestEngine(initial_balance=10_000.0, learn=True)
    result = await engine.run(history)

    print(f"bars={result.bars} symbol={SYMBOL}")
    print(f"stats: {format_stats(result.stats)}")
    print(f"final equity: {result.final_equity:.2f} (start 10000.00)")
    best = engine.patterns.top(3)
    if best:
        print("top patterns:")
        for p in best:
            print(f"  {p['regime']}/{p['root_cause']} n={p['count']} wr={p['winrate']}")
    print("SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
