"""Tests for market data primitives (Phase 2.7)."""

from datetime import UTC, datetime

from core.market_data import (
    Candle,
    MarketDataCache,
    Tick,
    TimeframeAggregator,
    bucket_start,
    expected_bars,
    find_gaps,
    resample_ticks,
    tf_seconds,
)


def _t(minute: int, second: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, 7, hour, minute, second, tzinfo=UTC)  # Wednesday


def test_tf_seconds() -> None:
    assert tf_seconds("M1") == 60
    assert tf_seconds("M5") == 300
    assert tf_seconds("H1") == 3600
    assert tf_seconds("D1") == 86400


def test_bucket_start_floors() -> None:
    assert bucket_start(_t(0, 45), "M1") == _t(0, 0)
    assert bucket_start(_t(3, 10), "M5") == _t(0, 0)
    assert bucket_start(_t(7, 59), "M15") == _t(0, 0)
    assert bucket_start(_t(20, 0), "M15") == _t(15, 0)


def test_aggregator_builds_and_closes_candle() -> None:
    agg = TimeframeAggregator("XAUUSD", "M1")
    assert agg.add_tick(Tick("XAUUSD", _t(0, 5), bid=100.0, ask=100.2)) is None
    assert agg.add_tick(Tick("XAUUSD", _t(0, 30), bid=101.0, ask=101.2)) is None
    assert agg.add_tick(Tick("XAUUSD", _t(0, 55), bid=99.0, ask=99.2)) is None

    closed = agg.add_tick(Tick("XAUUSD", _t(1, 5), bid=100.0, ask=100.2))
    assert closed is not None
    assert closed.open == 100.1
    assert closed.high == 101.1
    assert closed.low == 99.1
    assert closed.close == 99.1
    assert closed.ticks == 3
    assert closed.time == _t(0, 0)


def test_aggregator_flush_returns_partial() -> None:
    agg = TimeframeAggregator("XAUUSD", "M5")
    agg.add_tick(Tick("XAUUSD", _t(2, 0), bid=100.0, ask=100.0))
    partial = agg.flush()
    assert partial is not None
    assert partial.close == 100.0


def test_resample_ticks() -> None:
    ticks = [
        Tick("XAUUSD", _t(0, 1), 100.0, 100.0),
        Tick("XAUUSD", _t(0, 30), 101.0, 101.0),
        Tick("XAUUSD", _t(1, 1), 102.0, 102.0),
        Tick("XAUUSD", _t(2, 1), 103.0, 103.0),
    ]
    candles = resample_ticks(ticks, "XAUUSD", "M1")
    assert len(candles) == 3  # 00:00, 00:01, 00:02
    assert candles[0].open == 100.0 and candles[0].close == 101.0
    assert candles[-1].close == 103.0


def test_cache_append_replace_and_latest() -> None:
    cache = MarketDataCache(maxlen=5)
    c1 = Candle("XAUUSD", "M1", _t(0, 0), 1, 1, 1, 1)
    c1b = Candle("XAUUSD", "M1", _t(0, 0), 2, 2, 2, 2)
    c2 = Candle("XAUUSD", "M1", _t(1, 0), 3, 3, 3, 3)
    cache.append(c1)
    cache.append(c1b)  # same bar -> replace
    cache.append(c2)
    rows = cache.latest("XAUUSD", "M1", 10)
    assert len(rows) == 2
    assert rows[0].open == 2  # replaced
    assert cache.last_price("XAUUSD") == 3


def test_expected_bars() -> None:
    assert expected_bars(_t(0, 0), _t(5, 0), "M1") == 5
    assert expected_bars(_t(0, 0), _t(0, 0), "M1") == 0


def test_find_gaps_detects_weekday_gap() -> None:
    candles = [
        Candle("XAUUSD", "M1", _t(0, 0), 1, 1, 1, 1),  # 00:00:00
        Candle("XAUUSD", "M1", _t(1, 0), 1, 1, 1, 1),  # 00:01:00
        Candle("XAUUSD", "M1", _t(5, 0), 1, 1, 1, 1),  # 00:05:00 (3 bars missing)
    ]
    gaps = find_gaps(candles, "M1")
    assert len(gaps) == 1
    assert gaps[0] == (_t(2, 0), _t(5, 0))


def test_find_gaps_ignores_weekend() -> None:
    fri = datetime(2026, 1, 9, 20, 0, tzinfo=UTC)  # Friday
    mon = datetime(2026, 1, 12, 0, 0, tzinfo=UTC)  # Monday
    candles = [
        Candle("XAUUSD", "H1", fri, 1, 1, 1, 1),
        Candle("XAUUSD", "H1", mon, 1, 1, 1, 1),
    ]
    assert find_gaps(candles, "H1") == []


def test_no_gaps_when_contiguous() -> None:
    candles = [Candle("XAUUSD", "M1", _t(i, 0), 1, 1, 1, 1) for i in range(5)]
    assert find_gaps(candles, "M1") == []
