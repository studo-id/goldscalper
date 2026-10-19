"""Tests for the technical division (6 indicator agents)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

from agents.divisions.technical import (
    Momentum,
    Pattern,
    SupportResistance,
    Trend,
    Volatility,
    Volume,
    build_technical_agents,
)
from agents.state import VETO_BUY, VETO_SELL, VOTE_BUY, VOTE_NEUTRAL, VOTE_SELL, SharedState
from core.market_data import Candle, tf_seconds

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
SYMBOL = "XAUUSD"

_UP = [(2350 + i, 2351 + i, 2349 + i, 2350.5 + i) for i in range(30)]
_DOWN = [(2375 - i, 2376 - i, 2374 - i, 2374.5 - i) for i in range(30)]


def _geo(start: float, rate: float, n: int = 30) -> list[tuple[float, float, float, float]]:
    out: list[tuple[float, float, float, float]] = []
    for i in range(n):
        c = start * (rate**i)
        out.append((c, c + 1, c - 1, c))
    return out


from collections.abc import Sequence


def _frame(tf: str, rows: Sequence[tuple[float | int, float | int, float | int, float | int]], vol: float = 0.0):
    step = tf_seconds(tf)
    return [
        Candle(SYMBOL, tf, BASE + timedelta(seconds=step * i), float(o), float(h), float(low), float(c), volume=vol)
        for i, (o, h, low, c) in enumerate(rows)
    ]


def state(**kw: object) -> SharedState:
    frames = kw.pop("frames", {})
    return SharedState(symbol=SYMBOL, frames=frames, **kw)  # type: ignore[arg-type]


def test_factory_returns_six() -> None:
    agents = build_technical_agents()
    assert {a.id for a in agents} == {
        "Tech-Trend",
        "Tech-Momentum",
        "Tech-Volatility",
        "Tech-Volume",
        "Tech-SupportResistance",
        "Tech-Pattern",
    }
    assert all(a.division == "technical" for a in agents)
    assert all(a.default_weight == 1.0 for a in agents)


async def test_trend_bull() -> None:
    sig = await Trend().evaluate(state(frames={"M15": _frame("M15", _UP)}))
    assert sig.vote == VOTE_BUY


async def test_trend_bear() -> None:
    sig = await Trend().evaluate(state(frames={"M15": _frame("M15", _DOWN)}))
    assert sig.vote == VOTE_SELL


async def test_trend_insufficient() -> None:
    sig = await Trend().evaluate(state(frames={"M15": _frame("M15", _UP[:5])}))
    assert sig.vote == VOTE_NEUTRAL


async def test_momentum_bull() -> None:
    sig = await Momentum().evaluate(state(frames={"M15": _frame("M15", _geo(2350, 1.002))}))
    assert sig.vote == VOTE_BUY


async def test_momentum_bear() -> None:
    sig = await Momentum().evaluate(state(frames={"M15": _frame("M15", _geo(2500, 0.998))}))
    assert sig.vote == VOTE_SELL


async def test_momentum_insufficient() -> None:
    sig = await Momentum().evaluate(state(frames={"M15": _frame("M15", _UP[:10])}))
    assert sig.vote == VOTE_NEUTRAL


async def test_volatility_is_neutral_with_regime() -> None:
    sig = await Volatility().evaluate(state(frames={"M15": _frame("M15", _UP)}))
    assert sig.vote == VOTE_NEUTRAL
    assert sig.metadata["regime"] in {"squeeze", "normal", "expansion"}


async def test_volatility_squeeze() -> None:
    rows = [(2350, 2350, 2350, 2350) for _ in range(25)]
    sig = await Volatility().evaluate(state(frames={"M15": _frame("M15", rows)}))
    assert sig.metadata["regime"] == "squeeze"


async def test_volume_high_up_bar() -> None:
    rows = [(2350, 2351, 2349, 2350) for _ in range(20)] + [(2350, 2352, 2349, 2351)]
    frame = _frame("M5", rows, vol=1.0)
    frame[-1] = Candle(SYMBOL, "M5", frame[-1].time, 2350, 2352, 2349, 2351, volume=6.0)
    sig = await Volume().evaluate(state(frames={"M5": frame}))
    assert sig.vote == VOTE_BUY


async def test_volume_high_down_bar() -> None:
    rows = [(2350, 2351, 2349, 2350) for _ in range(20)] + [(2351, 2351.5, 2348, 2349)]
    frame = _frame("M5", rows, vol=1.0)
    frame[-1] = Candle(SYMBOL, "M5", frame[-1].time, 2351, 2351.5, 2348, 2349, volume=6.0)
    sig = await Volume().evaluate(state(frames={"M5": frame}))
    assert sig.vote == VOTE_SELL


async def test_support_resistance_at_support() -> None:
    rows = [(2358, 2360, 2350, 2358) for _ in range(19)] + [(2351, 2352, 2350, 2350)]
    sig = await SupportResistance().evaluate(state(frames={"M15": _frame("M15", rows)}))
    assert sig.vote == VOTE_BUY


async def test_support_resistance_at_resistance() -> None:
    rows = [(2352, 2360, 2350, 2352) for _ in range(19)] + [(2359, 2360, 2358, 2360)]
    sig = await SupportResistance().evaluate(state(frames={"M15": _frame("M15", rows)}))
    assert sig.vote == VOTE_SELL


async def test_support_resistance_mid_range() -> None:
    rows = [(2355, 2360, 2350, 2355) for _ in range(20)]
    sig = await SupportResistance().evaluate(state(frames={"M15": _frame("M15", rows)}))
    assert sig.vote == VOTE_NEUTRAL


async def test_support_resistance_m1_micro_support_veto_sell() -> None:
    # M5 frames in mid range (2350 to 2360, close at 2353.0)
    m5_rows = [(2355, 2360, 2350, 2355) for _ in range(19)] + [(2354, 2355, 2352.5, 2353.0)]
    # M1 frames have local swing low (support) at 2352.8. Current price 2353.0 is within $1.20 buffer!
    m1_rows = [(2355, 2356, 2352.8, 2355) for _ in range(19)] + [(2354, 2355, 2352.8, 2353.0)]
    
    st = state(frames={"M5": _frame("M5", m5_rows), "M1": _frame("M1", m1_rows)})
    sig = await SupportResistance().evaluate(st)
    
    # Must activate hard VETO_SELL to prevent chasing the dip into M1 support!
    assert sig.veto == VETO_SELL
    assert "veto SELL" in sig.reasoning
    assert sig.metadata.get("micro_sr_event") == "AT_MICRO_SUPPORT"


async def test_support_resistance_m1_micro_resistance_veto_buy() -> None:
    # M5 frames in mid range (2350 to 2360, close at 2357.5)
    m5_rows = [(2355, 2360, 2350, 2355) for _ in range(19)] + [(2356, 2358, 2355, 2357.5)]
    # M1 frames have local swing high (resistance) at 2358.0. Current price 2357.5 is within $1.20 buffer!
    m1_rows = [(2355, 2358.0, 2354, 2355) for _ in range(19)] + [(2356, 2358.0, 2356, 2357.5)]
    
    st = state(frames={"M5": _frame("M5", m5_rows), "M1": _frame("M1", m1_rows)})
    sig = await SupportResistance().evaluate(st)
    
    # Must activate hard VETO_BUY to prevent buying at M1 local peak!
    assert sig.veto == VETO_BUY
    assert "veto BUY" in sig.reasoning
    assert sig.metadata.get("micro_sr_event") == "AT_MICRO_RESISTANCE"


async def test_pattern_bullish_engulfing() -> None:
    rows = [(2350, 2351, 2349, 2350), (2355, 2356, 2350, 2351), (2350, 2358, 2349, 2357)]
    sig = await Pattern().evaluate(state(frames={"M5": _frame("M5", rows)}))
    assert sig.vote == VOTE_BUY


async def test_pattern_bearish_engulfing() -> None:
    rows = [(2350, 2351, 2349, 2350), (2350, 2356, 2349, 2355), (2356, 2357, 2348, 2349)]
    sig = await Pattern().evaluate(state(frames={"M5": _frame("M5", rows)}))
    assert sig.vote == VOTE_SELL


async def test_pattern_hammer() -> None:
    rows = [(2350, 2351, 2349, 2350), (2350, 2351, 2349, 2350), (2350, 2351, 2340, 2350.3)]
    sig = await Pattern().evaluate(state(frames={"M5": _frame("M5", rows)}))
    assert sig.vote == VOTE_BUY


async def test_pattern_pinbar_at_support_ping_pong_buy() -> None:
    # 20 bars establishing support near 2350, then a hammer pinbar at 2350
    rows = [(2355, 2358, 2350, 2356) for _ in range(19)] + [(2351, 2352, 2348, 2351.8)]
    sig = await Pattern().evaluate(state(frames={"M5": _frame("M5", rows)}))
    assert sig.vote == VOTE_BUY
    assert sig.confidence >= 0.70
    assert sig.metadata.get("ping_pong_side") == "BUY"


async def test_pattern_shooting_star_at_resistance_ping_pong_sell() -> None:
    # 20 bars establishing resistance near 2370, then a shooting star pinbar at 2370
    rows = [(2365, 2370, 2362, 2366) for _ in range(19)] + [(2369, 2373, 2368, 2368.2)]
    sig = await Pattern().evaluate(state(frames={"M5": _frame("M5", rows)}))
    assert sig.vote == VOTE_SELL
    assert sig.confidence >= 0.70
    assert sig.metadata.get("ping_pong_side") == "SELL"

