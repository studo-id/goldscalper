"""Unit tests for StructuralGuard (Multi-TF S&R and Fibonacci Dynamic SL)."""

import pytest
from datetime import datetime, timezone
from agents.state import SharedState
from core.market_data import Candle
from core.mt5_connector import Position
from execution.position_manager import PositionManager
from execution.structural_guard import StructuralGuard, StructuralLevel


def _make_candles(tf: str, prices: list[tuple[float, float, float, float]]) -> list[Candle]:
    """Helper to create Candle objects from (open, high, low, close)."""
    now = datetime.now(timezone.utc)
    return [
        Candle(
            symbol="XAUUSD",
            timeframe=tf,
            time=now,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=100.0,
        )
        for o, h, l, c in prices
    ]


class MockMT5Client:
    def __init__(self) -> None:
        self.closed_tickets: list[int] = []

    async def close_position(self, ticket: int, price: float = 0.0) -> bool:
        self.closed_tickets.append(ticket)
        return True

    async def modify_position(self, ticket: int, sl: float | None = None, tp: float | None = None) -> bool:
        return True


def test_structural_guard_swing_extraction():
    guard = StructuralGuard(buffer_pips=4.0)

    # Generate M15 candles with clear swing low at 4100.0 and swing high at 4140.0
    m15_prices = [
        (4110.0, 4115.0, 4108.0, 4112.0),
        (4112.0, 4114.0, 4105.0, 4106.0),
        (4106.0, 4108.0, 4100.0, 4103.0),  # Swing low = 4100.0
        (4103.0, 4118.0, 4102.0, 4115.0),
        (4115.0, 4125.0, 4114.0, 4122.0),
        (4122.0, 4140.0, 4120.0, 4138.0),  # Swing high = 4140.0
        (4138.0, 4139.0, 4130.0, 4132.0),
        (4132.0, 4135.0, 4128.0, 4130.0),
        (4130.0, 4132.0, 4125.0, 4126.0),
        (4126.0, 4128.0, 4122.0, 4125.0),
    ]

    state = SharedState(
        symbol="XAUUSD",
        frames={"M15": _make_candles("M15", m15_prices)},
    )

    eval_buy = guard.evaluate_invalidation(
        side="BUY",
        entry_price=4125.0,
        current_price=4124.0,
        volume=0.04,
        state=state,
        max_risk_usd=8.0,
    )

    assert eval_buy.side == "BUY"
    assert not eval_buy.is_breached
    assert eval_buy.recommendation == "HOLD"
    # Line X must be below entry and provide breathing room
    assert eval_buy.level_x < 4125.0


def test_structural_guard_fibonacci_golden_pocket():
    guard = StructuralGuard(buffer_pips=4.0)

    # 40 bars uptrend: low at 4100.0, high at 4200.0 (Range = $100)
    prices = [(4100.0 + i, 4102.0 + i, 4099.0 + i, 4101.0 + i) for i in range(20)]
    prices += [(4120.0 + i * 4, 4122.0 + i * 4, 4118.0 + i * 4, 4121.0 + i * 4) for i in range(20)]

    state = SharedState(
        symbol="XAUUSD",
        frames={"H1": _make_candles("H1", prices)},
    )

    # Entry at 4150.0, current price at 4149.0 (pullback 10 pips)
    # With max_risk_usd = 20.0 on 0.04 lot -> boundary is 4145.0
    eval_buy = guard.evaluate_invalidation(
        side="BUY",
        entry_price=4150.0,
        current_price=4149.0,
        volume=0.04,
        state=state,
        max_risk_usd=20.0,
    )

    assert eval_buy.side == "BUY"
    assert eval_buy.level_x < 4150.0
    assert not eval_buy.is_breached
    assert eval_buy.recommendation == "HOLD"


def test_structural_guard_breach_detection():
    guard = StructuralGuard(buffer_pips=4.0)

    m15_prices = [
        (4110.0, 4115.0, 4108.0, 4112.0),
        (4112.0, 4114.0, 4105.0, 4106.0),
        (4106.0, 4108.0, 4100.0, 4103.0),  # Swing low = 4100.0
        (4103.0, 4118.0, 4102.0, 4115.0),
        (4115.0, 4125.0, 4114.0, 4122.0),
    ]

    state = SharedState(
        symbol="XAUUSD",
        frames={"M15": _make_candles("M15", m15_prices)},
    )

    # Price collapsed deeply below Line X
    eval_breached = guard.evaluate_invalidation(
        side="BUY",
        entry_price=4110.0,
        current_price=4090.0,
        volume=0.04,
        state=state,
        max_risk_usd=8.0,
    )

    assert eval_breached.is_breached is True
    assert eval_breached.recommendation == "CUT_LOSS"
    assert "STRUCTURAL BREACH" in eval_breached.reasoning


@pytest.mark.asyncio
async def test_position_manager_holds_on_structural_guard():
    client = MockMT5Client()
    pm = PositionManager(client=client)  # type: ignore[arg-type]

    # M15 support at 4113.0 (within budget of entry 4115.0)
    m15_prices = [
        (4114.0, 4116.0, 4113.5, 4115.0),
        (4115.0, 4116.0, 4113.0, 4114.0),  # Swing low = 4113.0
        (4114.0, 4117.0, 4113.2, 4116.0),
        (4116.0, 4118.0, 4114.0, 4115.5),
        (4115.5, 4117.0, 4114.0, 4115.0),
    ]

    state = SharedState(
        symbol="XAUUSD",
        frames={"M15": _make_candles("M15", m15_prices)},
    )

    now = datetime.now(timezone.utc)
    opened = datetime.fromtimestamp(now.timestamp() - 100, tz=timezone.utc)  # held 100s

    # Entry 4115.0, price 4113.5 (15 pips pullback, above support 4113.0 - buffer)
    pos = Position(
        ticket=12345,
        symbol="XAUUSD",
        side="BUY",
        volume=0.04,
        price_open=4115.0,
        sl=4095.0,
        tp=4135.0,
        price_current=4113.5,  # 15 pips minus ($0.60 per 0.04 = -$6.00 with spread)
        profit=-3.50,
        time=opened,
    )

    ctx = {
        "state": state,
        "live_avg_win": 5.0,
    }

    # At 100 seconds, old logic would have blindly triggered duration cut!
    # With StructuralGuard holding Line X, it MUST HOLD (no close)!
    actions = await pm.manage(pos, price=4113.5, now=now, context=ctx)
    assert "juggler_duration_loss_cut" not in actions
    assert "satpam_structural_cut" not in actions
    assert 12345 not in client.closed_tickets


def test_anti_wick_panic_protects_minor_wick_spike():
    """Verify ticket #4907471979 scenario: a 2-pip spike in first 15s is held, not cut!"""
    guard = StructuralGuard(buffer_pips=8.0)

    # Resistance swing at 4130.0
    h1_prices = [
        (4120.0, 4125.0, 4118.0, 4122.0),
        (4122.0, 4130.0, 4120.0, 4128.0),
        (4128.0, 4129.0, 4122.0, 4124.0),
        (4124.0, 4126.0, 4120.0, 4123.0),
        (4123.0, 4125.0, 4119.0, 4121.0),
    ]

    state = SharedState(
        symbol="XAUUSD",
        frames={"H1": _make_candles("H1", h1_prices)},
    )

    # SELL entered at 4128.50, Line X around 4130.80
    # Price spikes to 4131.00 (overshoot 2 pips) at held=15s
    eval_15s = guard.evaluate_invalidation(
        side="SELL",
        entry_price=4128.50,
        current_price=4131.00,
        volume=0.04,
        state=state,
        held_seconds=15.0,
        max_risk_usd=12.0,
    )

    # Anti-wick shield protects the 15s spike!
    assert eval_15s.is_breached is True
    assert eval_15s.is_hard_breached is False
    assert eval_15s.recommendation == "HOLD"
    assert "ANTI-WICK SHIELD" in eval_15s.reasoning

    # But at held=60s (candle closed past Line X), it confirms cut loss!
    eval_60s = guard.evaluate_invalidation(
        side="SELL",
        entry_price=4128.50,
        current_price=4131.00,
        volume=0.04,
        state=state,
        held_seconds=60.0,
        max_risk_usd=12.0,
    )

    assert eval_60s.is_hard_breached is True
    assert eval_60s.recommendation == "CUT_LOSS"
    assert "STRUCTURAL BREACH" in eval_60s.reasoning



