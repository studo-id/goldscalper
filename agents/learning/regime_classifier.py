"""Regime classifier.

Labels the current market into one of a small, stable set of regimes so the
learning loop can condition outcomes on context. Pure/deterministic.
"""

from __future__ import annotations

from typing import Any

from core.indicators import atr, ema_last
from core.market_data import Bars

REGIME_TREND_UP = "trend_up"
REGIME_TREND_DOWN = "trend_down"
REGIME_RANGE = "range"
REGIME_VOLATILE = "volatile"

REGIMES = (REGIME_TREND_UP, REGIME_TREND_DOWN, REGIME_RANGE, REGIME_VOLATILE)

_VOLATILE_ATR_PCT = 0.006
_TREND_SLOPE_PCT = 0.0012


def classify(
    *,
    atr_pct: float,
    slope_pct: float,
    volatile_atr_pct: float = _VOLATILE_ATR_PCT,
    trend_slope_pct: float = _TREND_SLOPE_PCT,
) -> str:
    """Classify from pre-computed features (all ratios, not prices)."""
    if atr_pct >= volatile_atr_pct:
        return REGIME_VOLATILE
    if abs(slope_pct) >= trend_slope_pct:
        return REGIME_TREND_UP if slope_pct > 0 else REGIME_TREND_DOWN
    return REGIME_RANGE


def classify_bars(bars: Bars) -> str:
    """Classify directly from an OHLC frame."""
    if bars.n < 22:
        return REGIME_RANGE
    close = bars.last_close or 1.0
    atr_val = atr(bars.highs, bars.lows, bars.closes, 14)
    fast_now = ema_last(bars.closes, 9)
    fast_prev = ema_last(bars.closes[:-3], 9)
    atr_pct = atr_val / close
    slope_pct = (fast_now - fast_prev) / close
    return classify(atr_pct=atr_pct, slope_pct=slope_pct)


def classify_state(state: Any, timeframe: str = "M15") -> str:
    """Classify from a :class:`~agents.state.SharedState`."""
    return classify_bars(Bars.for_timeframe(state, timeframe))


__all__ = [
    "REGIME_TREND_UP",
    "REGIME_TREND_DOWN",
    "REGIME_RANGE",
    "REGIME_VOLATILE",
    "REGIMES",
    "classify",
    "classify_bars",
    "classify_state",
]
