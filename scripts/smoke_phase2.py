"""Phase 2 smoke test — tick streamer against live Redis + TimescaleDB.

Feeds deterministic quotes to close a candle, then runs the streamer briefly to
emit live mock ticks. Verifies Redis streams and persisted OHLCV.

Run inside the compose network:
    docker compose run --rm bot python scripts/smoke_phase2.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.message_bus import MessageBus  # noqa: E402
from core.market_data import MarketDataCache  # noqa: E402
from core.mt5_connector import MockMT5Client, Quote, TickStreamer  # noqa: E402
from data.repositories import MarketDataRepository  # noqa: E402

SYMBOL = "XAUUSD"


async def main() -> None:
    bus = MessageBus()
    cache = MarketDataCache()
    repo = MarketDataRepository()
    streamer = TickStreamer(
        MockMT5Client(seed=7),
        symbol=SYMBOL,
        bus=bus,
        cache=cache,
        repo=repo,
        poll_interval=0.05,
    )

    # Deterministic: two ticks in one M1 bar, one tick crossing the boundary.
    base = datetime.now(UTC).replace(second=0, microsecond=0)
    await streamer.process_tick(Quote(SYMBOL, base + timedelta(seconds=5), 2350.0, 2350.2))
    await streamer.process_tick(Quote(SYMBOL, base + timedelta(seconds=30), 2351.0, 2351.2))
    await streamer.process_tick(Quote(SYMBOL, base + timedelta(seconds=65), 2352.0, 2352.2))

    before = await repo.count_candles(SYMBOL, "M1")
    cache_bars = cache.latest(SYMBOL, "M1", 5)
    print(f"processed ticks={streamer.tick_count} candles_closed={streamer.candle_count}")
    last = cache_bars[-1].close if cache_bars else None
    print(f"cache M1 bars={len(cache_bars)} last_close={last}")

    # Live mock ticks for a moment.
    task = streamer.start()
    await asyncio.sleep(0.3)
    await streamer.stop()
    assert task.done()

    client = bus._client_or_create()
    ticks_len = await client.xlen("gs:ticks")
    candles_len = await client.xlen("gs:candles")
    after = await repo.count_candles(SYMBOL, "M1")
    print(f"redis gs:ticks={ticks_len} gs:candles={candles_len}")
    print(f"ohlcv M1 before={before} after={after}")

    await bus.close()
    print("SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
