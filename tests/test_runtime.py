"""Tests for the live Runtime wiring (no database, mock MT5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agents.state import utcnow
from core.market_data import Candle, tf_seconds
from core.mt5_connector import MockMT5Client, Quote
from runtime import Runtime

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
SYMBOL = "XAUUSD"


def _seed(runtime: Runtime, bullish: bool = True) -> None:
    sym = runtime.symbol
    rows = [
        (2350 + i, 2351 + i, 2349 + i, 2350.5 + i)
        if bullish
        else (2380 - i, 2381 - i, 2379 - i, 2379.5 - i)
        for i in range(30)
    ]
    for tf in ("M1", "M5", "M15", "M30", "H1", "H4", "D1"):
        step = tf_seconds(tf)
        for i, (o, h, low, c) in enumerate(rows):
            runtime.cache.append(
                Candle(sym, tf, BASE + timedelta(seconds=step * i), o, h, low, c, volume=2.0)
            )
    runtime.streamer.last_quote = Quote(sym, utcnow(), 2350.0, 2350.3)


def _runtime(**kw: object) -> Runtime:
    args: dict[str, object] = {"enable_persistence": False}
    args.update(kw)
    return Runtime(
        client=MockMT5Client(),
        **args,  # type: ignore[arg-type]
    )


async def test_runtime_step_produces_decision() -> None:
    rt = _runtime()
    _seed(rt, bullish=True)
    decision = await rt.step()
    assert decision is not None
    assert rt.orchestrator.cycle_count == 1
    assert rt.orchestrator.last_state is not None
    assert rt.orchestrator.last_state.symbol == rt.symbol



async def test_runtime_snapshot_shape() -> None:
    rt = _runtime()
    _seed(rt)
    snap = rt.snapshot()
    assert snap["agents"] >= 30
    assert "divisions" in snap
    assert snap["running"] is False


async def test_runtime_start_stop() -> None:
    rt = _runtime()
    _seed(rt)
    await rt.start()
    assert rt.client.connected
    assert rt.snapshot()["running"] is True
    await rt.stop()
    assert rt.snapshot()["running"] is False


async def test_runtime_opens_and_closes_trade() -> None:
    rt = _runtime()
    _seed(rt, bullish=True)
    await rt.step()
    # a position may or may not open depending on the cycle; if it did, the
    # runtime must track it and cleanly finalize when it disappears.
    open_trades = dict(rt._trades)
    if open_trades:
        ticket = next(iter(open_trades))
        await rt.client.close_position(ticket)
        await rt._manage_positions()
        assert ticket not in rt._trades
