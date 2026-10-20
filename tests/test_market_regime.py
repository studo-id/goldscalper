"""Tests for the Market Lifecycle & Regime Detection Engine (GoldScalper)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

import pytest

from agents.divisions.technical import SupportResistance
from agents.state import VETO_ALL, VETO_BUY, VETO_SELL, VOTE_BUY, VOTE_NEUTRAL, VOTE_SELL, SharedState
from core.market_data import Candle, tf_seconds
from core.market_regime import (
    REGIME_EXHAUSTION_BEAR,
    REGIME_EXHAUSTION_BULL,
    REGIME_SIDEWAY,
    REGIME_TRENDING_BEAR,
    REGIME_TRENDING_BULL,
    detect_market_regime,
)

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
SYMBOL = "XAUUSD"


def _frame(tf: str, rows: list[tuple[float, float, float, float]]):
    step = tf_seconds(tf)
    return [
        Candle(SYMBOL, tf, BASE + timedelta(seconds=step * i), o, h, l, c, volume=100.0)
        for i, (o, h, l, c) in enumerate(rows)
    ]


def test_regime_sideway_consolidation() -> None:
    # Flat M5 bars between 2350 and 2360
    m5_rows = [(2355.0, 2360.0, 2350.0, 2355.0) for _ in range(25)]
    m1_rows = [(2355.0, 2358.0, 2352.0, 2355.0) for _ in range(25)]
    st = SharedState(symbol=SYMBOL, frames={"M5": _frame("M5", m5_rows), "M1": _frame("M1", m1_rows)})

    regime = detect_market_regime(st, 2355.0)
    assert regime.regime == REGIME_SIDEWAY
    assert regime.allow_dead_zone is True
    assert regime.is_trending is False
    assert regime.allow_trend_continuation is False


def test_regime_trending_bear_disables_dead_zone() -> None:
    # Synchronized falling M5 and M1 trend (active expansion, ~1.0-1.5 ATR from mean)
    m5_rows = [(2360.0 - (i * 0.4), 2360.5 - (i * 0.4), 2359.0 - (i * 0.4), 2359.5 - (i * 0.4)) for i in range(25)]
    m1_rows = [(2354.0 - (i * 0.2), 2354.5 - (i * 0.2), 2353.5 - (i * 0.2), 2353.8 - (i * 0.2)) for i in range(25)]
    st = SharedState(symbol=SYMBOL, frames={"M5": _frame("M5", m5_rows), "M1": _frame("M1", m1_rows)})

    regime = detect_market_regime(st, 2349.0)
    assert regime.regime == REGIME_TRENDING_BEAR
    assert regime.allow_dead_zone is False  # DEAD ZONE IS DISABLED!
    assert regime.allow_trend_continuation is True
    assert regime.direction == "SELL"


def test_regime_trending_bull_disables_dead_zone() -> None:
    # Synchronized rising M5 and M1 trend (active expansion, ~1.0-1.5 ATR from mean)
    m5_rows = [(2340.0 + (i * 0.4), 2341.0 + (i * 0.4), 2339.5 + (i * 0.4), 2340.5 + (i * 0.4)) for i in range(25)]
    m1_rows = [(2346.0 + (i * 0.2), 2347.0 + (i * 0.2), 2345.5 + (i * 0.2), 2346.8 + (i * 0.2)) for i in range(25)]
    st = SharedState(symbol=SYMBOL, frames={"M5": _frame("M5", m5_rows), "M1": _frame("M1", m1_rows)})

    regime = detect_market_regime(st, 2351.0)
    assert regime.regime == REGIME_TRENDING_BULL
    assert regime.allow_dead_zone is False  # DEAD ZONE IS DISABLED!
    assert regime.allow_trend_continuation is True
    assert regime.direction == "BUY"


def test_regime_exhaustion_bear_bans_continuation() -> None:
    # Deep, overextended drop (> 2.3 ATR below EMA9)
    m5_rows = [(2365.0 - (i * 0.8), 2366.0 - (i * 0.8), 2364.0 - (i * 0.8), 2364.5 - (i * 0.8)) for i in range(25)]
    m1_rows = [(2350.0 - (i * 0.6), 2350.5 - (i * 0.6), 2348.0 - (i * 0.6), 2348.5 - (i * 0.6)) for i in range(25)]
    st = SharedState(symbol=SYMBOL, frames={"M5": _frame("M5", m5_rows), "M1": _frame("M1", m1_rows)})

    regime = detect_market_regime(st, 2330.0)
    assert regime.regime == REGIME_EXHAUSTION_BEAR
    assert regime.is_exhausted is True
    assert regime.allow_trend_continuation is False  # BANNED FROM SELLING AT EXHAUSTED FLOOR!


@pytest.mark.asyncio
async def test_support_resistance_trending_bear_allows_continuation_sell() -> None:
    # When market is trending down, SupportResistance should vote SELL and NOT block with VETO_SELL or VETO_ALL
    m5_rows = [(2360.0 - (i * 0.4), 2360.5 - (i * 0.4), 2359.0 - (i * 0.4), 2359.5 - (i * 0.4)) for i in range(25)]
    m1_rows = [(2354.0 - (i * 0.2), 2354.5 - (i * 0.2), 2353.5 - (i * 0.2), 2353.8 - (i * 0.2)) for i in range(25)]
    st = SharedState(symbol=SYMBOL, frames={"M5": _frame("M5", m5_rows), "M1": _frame("M1", m1_rows)})

    sig = await SupportResistance().evaluate(st)
    assert sig.vote == VOTE_SELL
    # Should NOT have VETO_ALL (dead zone disabled) and should NOT have VETO_SELL
    assert sig.veto != VETO_ALL
    assert sig.veto != VETO_SELL
    assert sig.veto == VETO_BUY  # Forbids buying against the downtrend


@pytest.mark.asyncio
async def test_support_resistance_micro_exhaustion_bounce_vetoes_sell() -> None:
    # When market has overall bear trend but M1 and M5 are both currently bouncing bullish (green),
    # SupportResistance should trigger MICRO_EXHAUSTION_BOUNCE and VETO_SELL!
    # Prior M5 bars dropping, but last M5 is bullish green (close > open)
    m5_rows = [(2360.0 - (i * 0.4), 2360.5 - (i * 0.4), 2359.0 - (i * 0.4), 2359.5 - (i * 0.4)) for i in range(24)]
    m5_rows.append((2349.0, 2351.5, 2348.8, 2351.2))  # last M5 green
    # Prior M1 bars dropping, but last M1 is bullish green
    m1_rows = [(2354.0 - (i * 0.2), 2354.5 - (i * 0.2), 2353.5 - (i * 0.2), 2353.8 - (i * 0.2)) for i in range(23)]
    m1_rows.append((2349.0, 2350.5, 2348.8, 2350.2))  # M1 close > open
    m1_rows.append((2350.2, 2351.4, 2350.0, 2351.2))  # M1 close > open
    st = SharedState(symbol=SYMBOL, frames={"M5": _frame("M5", m5_rows), "M1": _frame("M1", m1_rows)})

    sig = await SupportResistance().evaluate(st)
    assert sig.veto == VETO_SELL
    assert sig.metadata.get("micro_sr_event") == "MICRO_EXHAUSTION_BOUNCE"

