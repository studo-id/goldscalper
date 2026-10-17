"""Tests for the backtest harness (sim broker, metrics, engine)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backtest.engine import BacktestEngine
from backtest.metrics import compute_stats, max_drawdown
from backtest.sim_broker import SimBroker
from core.market_data import Candle, tf_seconds
from core.mt5_connector import SIDE_BUY, SIDE_SELL, OrderRequest

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
SYMBOL = "XAUUSD"


async def test_sim_broker_buy_pnl() -> None:
    b = SimBroker(SYMBOL, contract_size=100.0, spread=0.30)
    await b.connect()
    b.set_market(2350.0, BASE)
    res = await b.order_send(OrderRequest(symbol=SYMBOL, side=SIDE_BUY, volume=1.0))
    assert res.ok and res.ticket is not None
    assert res.price == 2350.15  # ask = mid + half spread
    b.set_market(2351.0, BASE)
    positions = await b.positions(SYMBOL)
    assert positions[0].profit > 0
    close = await b.close_position(res.ticket, price=2351.0)
    assert close.ok
    assert b.realized[0]["pnl"] == (2351.0 - 2350.15) * 100.0


async def test_sim_broker_sell_pnl() -> None:
    b = SimBroker(SYMBOL, contract_size=100.0, spread=0.30)
    await b.connect()
    b.set_market(2350.0, BASE)
    res = await b.order_send(OrderRequest(symbol=SYMBOL, side=SIDE_SELL, volume=0.5))
    assert res.price == 2349.85  # bid = mid - half spread
    close = await b.close_position(res.ticket, price=2349.0)
    assert close.ok
    assert b.realized[0]["pnl"] > 0


async def test_sim_broker_partial_close() -> None:
    b = SimBroker(SYMBOL)
    await b.connect()
    b.set_market(2350.0, BASE)
    res = await b.order_send(OrderRequest(symbol=SYMBOL, side=SIDE_BUY, volume=1.0))
    await b.close_position(res.ticket, price=2351.0, volume=0.5)
    positions = await b.positions(SYMBOL)
    assert len(positions) == 1
    assert positions[0].volume == 0.5


def test_max_drawdown() -> None:
    assert max_drawdown([100.0, 90.0, 95.0, 80.0], 100.0) == 0.2
    assert max_drawdown([100.0, 110.0], 100.0) == 0.0


def test_compute_stats() -> None:
    realized = [{"pnl": 20.0}, {"pnl": -10.0}, {"pnl": 30.0}]
    stats = compute_stats(realized, [10000.0, 10040.0], 10000.0)
    assert stats["trades"] == 3
    assert stats["wins"] == 2
    assert stats["winrate"] == 0.6667
    assert stats["profit_factor"] == 5.0
    assert stats["total_pnl"] == 40.0


def _history(bars: int = 90) -> dict[str, list[Candle]]:
    def series(tf: str, n: int) -> list[Candle]:
        step = tf_seconds(tf)
        out: list[Candle] = []
        price = 2350.0
        for i in range(n):
            drift = 0.6 if i < n // 2 else -0.6
            o = price
            c = price + drift
            h = max(o, c) + 0.5
            low = min(o, c) - 0.5
            out.append(
                Candle(SYMBOL, tf, BASE + timedelta(seconds=step * i), o, h, low, c, volume=5.0)
            )
            price = c
        return out

    return {
        "M1": series("M1", bars),
        "M5": series("M5", bars),
        "M15": series("M15", bars),
        "M30": series("M30", bars),
        "H1": series("H1", bars),
        "H4": series("H4", bars),
        "D1": series("D1", bars),
    }


async def test_engine_runs_and_reports() -> None:
    engine = BacktestEngine(initial_balance=10_000.0, learn=False)
    result = await engine.run(_history(90))
    assert result.bars == 90
    assert len(result.equity_curve) == 90
    assert "trades" in result.stats
    assert "max_drawdown_pct" in result.stats
    assert engine.registry.size >= 30
