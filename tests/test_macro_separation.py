"""Tests for Macro Timeframe separation (D1 Stop Loss Invalidation & H4 Adaptive TP)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

from agents.base import AgentSignal
from agents.divisions.timeframe.scouts import D1Macro, H4Structure
from agents.state import SharedState, utcnow
from config.settings import Settings
from core.market_data import Candle, tf_seconds
from core.mt5_connector import MockMT5Client, Position, SIDE_BUY, SIDE_SELL
from execution.position_manager import PositionManager
from spk.decision import ACTION_BUY, ACTION_SELL
from spk.veto import VetoParams, evaluate as veto_evaluate

BASE = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)


from typing import Any, Sequence

def _frame(tf: str, rows: Sequence[tuple[Any, Any, Any, Any]]) -> list[Candle]:
    step = tf_seconds(tf)
    return [
        Candle("XAUUSD", tf, BASE + timedelta(seconds=step * i), float(o), float(h), float(l), float(c))
        for i, (o, h, l, c) in enumerate(rows)
    ]


@pytest.mark.asyncio
async def test_d1_entry_veto_disabled_suppresses_veto(monkeypatch) -> None:
    from config.settings import settings
    monkeypatch.setattr(settings, "d1_entry_veto_enabled", False)

    rows = [(2350, 2360, 2340, 2350), (2355, 2361, 2354, 2359)]
    st = SharedState(symbol="XAUUSD", frames={"D1": _frame("D1", rows)})

    d1 = await D1Macro().evaluate(st)
    assert d1.veto is None
    assert st.extra.get("d1_pdh") == 2360.0
    assert st.extra.get("d1_pdl") == 2340.0


@pytest.mark.asyncio
async def test_h4_entry_veto_disabled_suppresses_veto(monkeypatch) -> None:
    from config.settings import settings
    monkeypatch.setattr(settings, "h4_entry_veto_enabled", False)

    rows: list[tuple[float, float, float, float]] = [(2350.0, 2360.0, 2340.0, 2350.0)] * 40
    rows[-1] = (2350.0, 2360.0, 2340.0, 2359.5)  # in supply zone
    st = SharedState(symbol="XAUUSD", frames={"H4": _frame("H4", rows)})

    h4 = await H4Structure().evaluate(st)
    assert h4.veto is None
    assert "h4_bias" in st.extra


@pytest.mark.asyncio
async def test_spk_bypasses_d1_and_h4_when_entry_veto_disabled() -> None:
    st = SharedState(symbol="XAUUSD")
    sig_d1 = AgentSignal(agent_id="TF-D1-Macro", division="timeframe", vote=1, confidence=0.8, veto="VETO_BUY")
    sig_h4 = AgentSignal(agent_id="TF-H4-Structure", division="timeframe", vote=-1, confidence=0.75, veto="VETO_SELL")

    # When enabled (default)
    p_enabled = VetoParams(d1_entry_veto_enabled=True, h4_entry_veto_enabled=True)
    res_buy = veto_evaluate([sig_d1], st, ACTION_BUY, p_enabled)
    assert res_buy.confidence_delta < 0  # HTF macro penalty applied

    # When disabled (Akun 2 Lab)
    p_disabled = VetoParams(d1_entry_veto_enabled=False, h4_entry_veto_enabled=False)
    res_buy_clean = veto_evaluate([sig_d1], st, ACTION_BUY, p_disabled)
    assert res_buy_clean.confidence_delta == 0.0  # Completely ignored

    res_sell_clean = veto_evaluate([sig_h4], st, ACTION_SELL, p_disabled)
    assert res_sell_clean.confidence_delta == 0.0


@pytest.mark.asyncio
async def test_macro_d1_sl_invalidation_cut() -> None:
    client = MockMT5Client()
    s = Settings(macro_d1_sl_invalidation_enabled=True)
    pm = PositionManager(client, settings=s)

    # Long position opened at 2350
    pos = Position(
        ticket=101,
        symbol="XAUUSD",
        side=SIDE_BUY,
        volume=0.02,
        price_open=2350.0,
        sl=2330.0,
        tp=2370.0,
        profit=-10.0,
        time=utcnow() - timedelta(seconds=120),
    )
    pm.track(pos)

    # Previous Day Low is 2340.0. Current price dropped to 2339.0 (< PDL - 0.50 buffer)
    st = SharedState(symbol="XAUUSD")
    st.extra["d1_pdh"] = 2360.0
    st.extra["d1_pdl"] = 2340.0

    actions = await pm.manage(pos, price=2339.0, context={"state": st})
    assert "macro_d1_sl_invalidation_cut" in actions


@pytest.mark.asyncio
async def test_macro_h4_adaptive_tp_counter_scalp() -> None:
    client = MockMT5Client()
    s = Settings(macro_h4_adaptive_tp_enabled=True, juggler_enabled=True)
    pm = PositionManager(client, settings=s)

    # Long position opened at 2350, current profit is +$3.50 (counter H4 downtrend)
    pos = Position(
        ticket=102,
        symbol="XAUUSD",
        side=SIDE_BUY,
        volume=0.02,
        price_open=2350.0,
        sl=2345.0,
        tp=2365.0,
        profit=3.50,
        time=utcnow() - timedelta(seconds=30),
    )
    pm.track(pos)

    st = SharedState(symbol="XAUUSD")
    st.extra["h4_bias"] = "BEARISH"  # opposing our BUY

    actions = await pm.manage(pos, price=2351.75, context={"state": st})
    assert "macro_h4_fast_harvest" in actions
