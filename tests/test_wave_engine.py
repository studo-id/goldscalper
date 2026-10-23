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


def test_wave_engine_blocks_counter_trend_chaining() -> None:
    engine = DataDrivenWaveEngine()
    rows = [(2350.0 + (i * 0.2), 2351.0 + (i * 0.2), 2349.5 + (i * 0.2), 2350.5 + (i * 0.2)) for i in range(30)]
    frames = {"M5": _frame("M5", rows), "M1": _frame("M1", rows)}
    st = SharedState(
        symbol="XAUUSD",
        frames=frames,
        extra={"session_waterfall_bear": True, "market_regime": "TRENDING_BEAR"},
    )

    # 1. Trade #1 (chain_count = 0 -> 1): Initial counter-trend scalp is permitted
    cap1 = engine.evaluate_wave(st, candidate_direction="BUY", current_price=2356.5)
    assert cap1.can_chain is True

    # Record trade #1 opened and closed with profit
    engine.record_trade_opened("BUY", price=2356.0)
    engine.record_trade_closed(is_win=True, direction="BUY")
    assert engine.chain_count == 1

    # 2. Trade #2 (chain_count >= 1): Attempting wave continuation against active bear trend
    # MUST BE EXHAUSTED AND BLOCKED (Single-shot counter-trend rule)!
    cap2 = engine.evaluate_wave(st, candidate_direction="BUY", current_price=2356.8)
    assert cap2.capacity == CAPACITY_EXHAUSTED
    assert cap2.can_chain is False
    assert "single-shot only" in cap2.reason


def test_wave_engine_resets_idle_chain_count_on_evaluation() -> None:
    """Ensure that after idle_reset_s passes, chain_count resets to 0 during evaluation."""
    engine = DataDrivenWaveEngine(idle_reset_s=150)
    now = 1000.0

    # Trade 1 and 2 win
    engine.record_trade_opened("SELL", price=4130.0, timestamp=now)
    engine.record_trade_opened("SELL", price=4125.0, timestamp=now + 20.0)
    engine.record_trade_closed(is_win=True, direction="SELL", timestamp=now + 30.0)
    assert engine.chain_count == 2

    rows = [(2350.0, 2351.0, 2349.5, 2350.5) for _ in range(30)]
    frames = {"M5": _frame("M5", rows), "M1": _frame("M1", rows)}
    st = SharedState(symbol="XAUUSD", frames=frames)

    # 400 seconds later (> idle_reset_s=150s), evaluating wave must reset chain_count to 0
    cap = engine.evaluate_wave(st, candidate_direction="SELL", current_price=2350.0, timestamp=now + 400.0)
    assert engine.chain_count == 0
    assert engine.current_direction is None
    assert cap.can_chain is True


def test_wave_engine_directional_extension_does_not_penalize_pullback() -> None:
    """Ensure that a SELL candidate when price is above EMA9 (pullback to resistance) has 0.0 extension."""
    engine = DataDrivenWaveEngine()
    # M5 rows around 4000.0 (EMA9 ~ 4000.0)
    rows = [(4000.0, 4002.0, 3998.0, 4000.0) for _ in range(30)]
    frames = {"M5": _frame("M5", rows), "M1": _frame("M1", rows)}
    st = SharedState(symbol="XAUUSD", frames=frames)

    # Price has rallied to 4015.0 (above EMA9 4000.0). For a SELL, this is a pullback to resistance!
    cap_sell = engine.evaluate_wave(st, candidate_direction="SELL", current_price=4015.0)
    assert cap_sell.extension_atr == 0.0
    assert cap_sell.can_chain is True
    assert cap_sell.capacity == CAPACITY_HEALTHY


