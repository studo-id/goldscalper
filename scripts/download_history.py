"""Download historical OHLCV from MT5 into TimescaleDB.

Resumable and chunked: for each timeframe it fetches in fixed-size windows and
upserts into ``ohlcv``, so re-runs only fill what is missing.

Examples:
    # Full 2 years, all timeframes (real MT5 on Windows host)
    python scripts/download_history.py --years 2

    # Resume from the last stored candle
    python scripts/download_history.py --years 2 --resume

    # Dev/dry run with synthetic data, single timeframe, 7 days
    python scripts/download_history.py --mock --timeframes M1 --days 7
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.logging import configure_logging, get_logger  # noqa: E402
from config.settings import settings  # noqa: E402
from core.market_data import TIMEFRAME_SECONDS, find_gaps, tf_seconds  # noqa: E402
from core.mt5_connector import MockMT5Client, create_client  # noqa: E402
from data.repositories import MarketDataRepository  # noqa: E402

log = get_logger("scripts.download_history")

ALL_TFS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]

# Rough bars-per-chunk targets to bound memory per request.
_CHUNK_BARS = {
    "M1": 20_000,
    "M5": 20_000,
    "M15": 20_000,
    "M30": 12_000,
    "H1": 8_000,
    "H4": 6_000,
    "D1": 3_000,
}


def _chunk_delta(timeframe: str) -> timedelta:
    bars = _CHUNK_BARS.get(timeframe, 10_000)
    return timedelta(seconds=bars * tf_seconds(timeframe))


async def _download_timeframe(
    client,
    repo: MarketDataRepository,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    resume: bool,
) -> tuple[int, int, int]:
    """Download one timeframe. Returns (saved, chunks, gaps)."""
    if resume:
        last = await repo.last_candle_time(symbol, timeframe)
        if last is not None:
            start = max(start, last + timedelta(seconds=tf_seconds(timeframe)))
            log.info("[%s] resuming from %s", timeframe, start.isoformat())

    if start >= end:
        log.info("[%s] up to date", timeframe)
        return 0, 0, 0

    step = _chunk_delta(timeframe)
    saved = 0
    chunks = 0
    collected = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + step, end)
        try:
            candles = await client.copy_rates(symbol, timeframe, cursor, chunk_end)
        except Exception as exc:  # noqa: BLE001
            log.error("[%s] fetch failed %s..%s: %s", timeframe, cursor, chunk_end, exc)
            break
        if candles:
            saved += await repo.save_candles(candles)
            collected.extend(candles)
        chunks += 1
        log.info(
            "[%s] %s..%s -> %d candles (total saved=%d)",
            timeframe,
            cursor.date(),
            chunk_end.date(),
            len(candles),
            saved,
        )
        cursor = chunk_end

    gaps = find_gaps(collected, timeframe) if collected else []
    if gaps:
        log.warning("[%s] detected %d gap(s), e.g. %s", timeframe, len(gaps), gaps[0])
    return saved, chunks, len(gaps)


async def download(
    symbol: str,
    timeframes: list[str],
    start: datetime,
    end: datetime,
    resume: bool,
    use_mock: bool,
) -> None:
    repo = MarketDataRepository()
    if use_mock:
        client = MockMT5Client()
    else:
        client = create_client(settings)
    await client.connect()
    try:
        for tf in timeframes:
            saved, chunks, gaps = await _download_timeframe(
                client, repo, symbol, tf, start, end, resume
            )
            total = await repo.count_candles(symbol, tf)
            log.info(
                "[%s] DONE saved=%d chunks=%d gaps=%d total_in_db=%d",
                tf, saved, chunks, gaps, total,
            )
    finally:
        await client.disconnect()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download MT5 history into TimescaleDB")
    p.add_argument("--symbol", default=settings.mt5_symbol)
    p.add_argument("--timeframes", default=",".join(ALL_TFS), help="comma list, e.g. M1,H1,D1")
    p.add_argument("--years", type=float, default=2.0, help="history depth (default 2)")
    p.add_argument("--days", type=float, default=None, help="override: depth in days")
    p.add_argument("--resume", action="store_true", help="continue from last stored candle")
    p.add_argument("--mock", action="store_true", help="use synthetic data (no MT5 needed)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    configure_logging()

    end = datetime.now(UTC).replace(second=0, microsecond=0)
    if args.days is not None:
        start = end - timedelta(days=args.days)
    else:
        start = end - timedelta(days=int(args.years * 365))

    tfs = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]
    for tf in tfs:
        if tf not in TIMEFRAME_SECONDS:
            raise SystemExit(f"unknown timeframe: {tf}")

    log.info(
        "downloading %s %s from %s to %s (mock=%s, resume=%s)",
        args.symbol, tfs, start.isoformat(), end.isoformat(), args.mock, args.resume,
    )
    asyncio.run(download(args.symbol, tfs, start, end, args.resume, args.mock))


if __name__ == "__main__":
    main()
