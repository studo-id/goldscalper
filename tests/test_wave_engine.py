"""Unit tests for DataDrivenWaveEngine."""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import pytest

from agents.state import SharedState
from core.market_data import Candle, tf_seconds
from core.wave_engine import (
    CAPACITY_EXHAUSTED,
    CAPACITY_HEALTHY,
    CAPACITY_MATURE,
    DataDrivenWaveEngine,
)
from spk.decision import ACTION_BUY, ACTION_SELL
from spk.veto import evaluate

UTC = timezone.utc
BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
SYMBOL = "XAUUSD"


def _frame(tf: str, rows: Sequence[tuple[float | int, float | int, float | int, float | int]], vol: float = 0.0) -> list[Candle]:
    step = tf_seconds(tf)
    return [
        Candle(SYMBOL, tf, BASE + timedelta(seconds=step * i), float(o), float(h), float(low), float(c), volume=vol)
        for i, (o, h, low, c) in enumerate(rows)
    ]


def test_wave_engine_tracks_chains_and_broken_cooldown() -> None:
    engine = DataDrivenWaveEngine(broken_wave_cooldown_s=90)
    now = 1000.0

    # 1. Open first SELL trade
    engine.record_trade_opened("SELL", price=4130.0, timestamp=now)
    assert engine.current_direction == "SELL"
    assert engine.origin_price == 4130.0
    assert engine.chain_count == 1

    # 2. Open second SELL trade in same wave
    engine.record_trade_opened("SELL", price=4128.0, timestamp=now + 20.0)
    assert engine.chain_count == 2
    assert engine.origin_price == 4130.0  # Kept original anchor

    # 3. Trade closes with loss -> Broken wave!
    engine.record_trade_closed(is_win=False, direction="SELL", timestamp=now + 30.0)
    assert engine.current_direction is None
    assert engine.chain_count == 0

    # Check cooldown: SELL must be blocked for 90s (until 1120.0)
    in_cd_sell, rem_sell = engine.is_in_broken_cooldown("SELL", timestamp=now + 40.0)
    assert in_cd_sell is True
    assert rem_sell == 80  # 90 - 10 elapsed

    # Crucial scalper requirement: BUY is NOT in cooldown!
    in_cd_buy, _ = engine.is_in_broken_cooldown("BUY", timestamp=now + 40.0)
    assert in_cd_buy is False

    # After 95s (now + 125.0): cooldown expired
    in_cd_sell_expired, _ = engine.is_in_broken_cooldown("SELL", timestamp=now + 125.0)
    assert in_cd_sell_expired is False


def test_wave_capacity_extension_projection() -> None:
    engine = DataDrivenWaveEngine()
    rows = [(2350.0 + (i * 0.2), 2351.0 + (i * 0.2), 2349.5 + (i * 0.2), 2350.5 + (i * 0.2)) for i in range(30)]
    frames = {"M5": _frame("M5", rows), "M1": _frame("M1", rows)}
    st = SharedState(symbol="XAUUSD", frames=frames)

    # 1. Healthy wave: current price near origin
    engine.record_trade_opened("BUY", price=2356.0, timestamp=100.0)
    cap = engine.evaluate_wave(st, candidate_direction="BUY", current_price=2356.5, timestamp=110.0)
    assert cap.capacity == CAPACITY_HEALTHY
    assert cap.can_chain is True
    assert cap.size_multiplier == 1.0

    # 2. Mature wave: price extended > 1.8x ATR (ATR ~ 1.50)
    cap_mature = engine.evaluate_wave(st, candidate_direction="BUY", current_price=2359.2, timestamp=110.0)
    assert cap_mature.capacity in (CAPACITY_MATURE, CAPACITY_EXHAUSTED)
    if cap_mature.capacity == CAPACITY_MATURE:
        assert cap_mature.size_multiplier == 0.75
        assert cap_mature.can_chain is True

    # 3. Overextended / Exhausted wave: price extended > 2.5x ATR (~$4.50 from 2356)
    cap_exhausted = engine.evaluate_wave(st, candidate_direction="BUY", current_price=2362.0, timestamp=110.0)
    assert cap_exhausted.capacity == CAPACITY_EXHAUSTED
    assert cap_exhausted.is_exhausted is True
    assert cap_exhausted.can_chain is False
    assert cap_exhausted.size_multiplier == 0.0


def test_spk_veto_enforces_broken_wave_cooldown() -> None:
    engine = DataDrivenWaveEngine(broken_wave_cooldown_s=90)
    now = time.time()
    # Arm broken wave on SELL
    engine.record_trade_closed(is_win=False, direction="SELL", timestamp=now)

    rows = [(2350.0 + (i * 0.2), 2351.0 + (i * 0.2), 2349.5 + (i * 0.2), 2350.5 + (i * 0.2)) for i in range(30)]
    frames = {"M5": _frame("M5", rows), "M1": _frame("M1", rows)}
    st = SharedState(symbol="XAUUSD", frames=frames, extra={"wave_engine": engine})

    # SELL must be blocked by VETO_WAVE
    veto_sell = evaluate([], st, direction=ACTION_SELL)
    assert veto_sell.hard is True
    assert "VETO_WAVE" in (veto_sell.reason or "")

    # BUY must NOT be blocked by wave engine!
    veto_buy = evaluate([], st, direction=ACTION_BUY)
    assert not (veto_buy.hard and "VETO_WAVE" in (veto_buy.reason or ""))
