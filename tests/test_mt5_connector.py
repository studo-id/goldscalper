"""Tests for the MT5 connector and tick streamer (Phase 2.7)."""

from datetime import UTC, datetime, timedelta

from agents.message_bus import MemoryBus
from config.settings import settings
from core.market_data import MarketDataCache
from core.mt5_connector import (
    MockMT5Client,
    Quote,
    TickStreamer,
    create_client,
)


async def test_mock_connect_and_tick() -> None:
    client = MockMT5Client(seed=1)
    assert await client.connect() is True
    assert client.connected is True
    q = await client.symbol_tick("XAUUSD")
    assert q is not None
    assert q.ask > q.bid
    assert q.spread > 0
    tick = q.as_tick()
    assert tick.symbol == "XAUUSD"
    await client.disconnect()
    assert client.connected is False


async def test_mock_copy_rates_count_and_order() -> None:
    client = MockMT5Client(seed=2)
    await client.connect()
    start = datetime(2026, 1, 7, 0, 0, tzinfo=UTC)
    end = start + timedelta(minutes=10)
    candles = await client.copy_rates("XAUUSD", "M1", start, end)
    assert len(candles) == 10
    assert all(c.timeframe == "M1" for c in candles)
    assert all(c.high >= c.low for c in candles)
    times = [c.time for c in candles]
    assert times == sorted(times)
    # deterministic seed -> identical on re-run
    again = await client.copy_rates("XAUUSD", "M1", start, end)
    assert [c.close for c in candles] == [c.close for c in again]
    await client.disconnect()


def test_create_client_returns_mock_when_configured() -> None:
    s = settings.model_copy(update={"mt5_mock": True, "mt5_bridge_url": ""})
    assert isinstance(create_client(s), MockMT5Client)


class _FakeRepo:
    def __init__(self) -> None:
        self.candles: list = []

    async def save_candles(self, candles: list) -> int:
        self.candles.extend(candles)
        return len(candles)


async def test_tick_streamer_publishes_and_closes_candle() -> None:
    bus = MemoryBus()
    cache = MarketDataCache()
    repo = _FakeRepo()
    streamer = TickStreamer(
        MockMT5Client(seed=3), symbol="XAUUSD", bus=bus, cache=cache, repo=repo
    )

    base = datetime(2026, 1, 7, 0, 0, tzinfo=UTC)
    await streamer.process_tick(Quote("XAUUSD", base + timedelta(seconds=5), 100.0, 100.2))
    await streamer.process_tick(Quote("XAUUSD", base + timedelta(seconds=30), 101.0, 101.2))
    # crosses into next minute -> M1 bar 00:00 closes
    await streamer.process_tick(Quote("XAUUSD", base + timedelta(seconds=65), 102.0, 102.2))

    assert len(bus.messages("gs:ticks")) == 3
    assert len(bus.messages("gs:candles")) == 1
    closed = cache.latest("XAUUSD", "M1", 1)
    assert len(closed) == 1
    assert closed[0].open == 100.1 and closed[0].close == 101.1
    assert len(repo.candles) == 1
    assert streamer.tick_count == 3
    assert streamer.candle_count == 1


async def test_tick_streamer_run_and_stop() -> None:
    import asyncio

    streamer = TickStreamer(MockMT5Client(seed=4), poll_interval=0.01)
    task = streamer.start()
    await asyncio.sleep(0.06)
    await streamer.stop()
    assert task.done()
    assert streamer.tick_count >= 1
    assert streamer.snapshot()["client"] == "MockMT5Client"
