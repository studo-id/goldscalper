"""Tests for the structure division (5 directional agents)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agents.divisions.structure import (
    Correlation,
    Liquidity,
    MarketStructure,
    Microstructure,
    Session,
    build_structure_agents,
)
from agents.state import VETO_BUY, VETO_SELL, VOTE_BUY, VOTE_NEUTRAL, VOTE_SELL, SharedState
from core.market_data import Candle, tf_seconds

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
SYMBOL = "XAUUSD"

from collections.abc import Sequence

_UP = [(2350 + i, 2351 + i, 2349 + i, 2350.5 + i) for i in range(12)]
_DOWN = [(2360 - i, 2361 - i, 2359 - i, 2359.5 - i) for i in range(12)]


def _frame(tf: str, rows: Sequence[tuple[float | int, float | int, float | int, float | int]], vol: float = 0.0):
    step = tf_seconds(tf)
    return [
        Candle(SYMBOL, tf, BASE + timedelta(seconds=step * i), float(o), float(h), float(low), float(c), volume=vol)
        for i, (o, h, low, c) in enumerate(rows)
    ]


def state(**kw: object) -> SharedState:
    frames = kw.pop("frames", {})
    return SharedState(symbol=SYMBOL, frames=frames, **kw)  # type: ignore[arg-type]


def test_factory_returns_five() -> None:
    agents = build_structure_agents()
    assert {a.id for a in agents} == {
        "Struct-MarketStructure",
        "Struct-Liquidity",
        "Struct-Session",
        "Struct-Microstructure",
        "Struct-Correlation",
    }
    assert all(a.division == "structure" for a in agents)
    assert all(a.default_weight == 1.3 for a in agents)


async def test_market_structure_bos_bull() -> None:
    st = state(frames={"M15": _frame("M15", _UP)})
    sig = await MarketStructure().evaluate(st)
    assert sig.vote == VOTE_BUY
    assert sig.metadata["event"] == "BOS_BULL"


async def test_market_structure_bos_bear() -> None:
    st = state(frames={"M15": _frame("M15", _DOWN)})
    sig = await MarketStructure().evaluate(st)
    assert sig.vote == VOTE_SELL
    assert sig.metadata["event"] == "BOS_BEAR"


async def test_market_structure_insufficient() -> None:
    st = state(frames={"M15": _frame("M15", _UP[:3])})
    sig = await MarketStructure().evaluate(st)
    assert sig.vote == VOTE_NEUTRAL


async def test_liquidity_bullish_fvg() -> None:
    rows = [
        (2350, 2351, 2349, 2350),
        (2352, 2353, 2351, 2352),
        (2360, 2361, 2359, 2360),
        (2362, 2363, 2361, 2362),
    ]
    st = state(frames={"M5": _frame("M5", rows)})
    sig = await Liquidity().evaluate(st)
    assert sig.vote == VOTE_BUY
    assert sig.metadata["bullish_fvg"] is True


async def test_liquidity_ssl_sweep() -> None:
    rows = [
        (2355, 2356, 2352, 2355),
        (2353, 2354, 2350, 2353),
        (2352, 2353, 2349, 2352),
        (2351, 2352, 2348, 2351),
        (2350, 2351, 2345, 2350),
    ]
    st = state(frames={"M5": _frame("M5", rows)})
    sig = await Liquidity().evaluate(st)
    assert sig.metadata["ssl_sweep"] is True
    assert sig.vote == VOTE_BUY


async def test_liquidity_neutral() -> None:
    rows = [(2350, 2350.5, 2349.5, 2350) for _ in range(6)]
    st = state(frames={"M5": _frame("M5", rows)})
    sig = await Liquidity().evaluate(st)
    assert sig.vote == VOTE_NEUTRAL


async def test_session_is_vote_neutral() -> None:
    st = state(session="london")
    sig = await Session().evaluate(st)
    assert sig.vote == VOTE_NEUTRAL
    assert sig.metadata["session"] == "london"
    assert sig.metadata["low_liquidity"] is False


async def test_session_flags_asia_low_liquidity() -> None:
    st = state(session="asia")
    sig = await Session().evaluate(st)
    assert sig.metadata["low_liquidity"] is True


async def test_microstructure_buy_pressure() -> None:
    rows = [(2350 + i, 2351 + i, 2350.5 + i, 2350.8 + i) for i in range(10)]
    st = state(frames={"M1": _frame("M1", rows, vol=2.0)}, spread_points=10)
    sig = await Microstructure().evaluate(st)
    assert sig.vote == VOTE_BUY


async def test_microstructure_sell_pressure() -> None:
    rows = [(2360 - i, 2360.5 - i, 2359 - i, 2359.2 - i) for i in range(10)]
    st = state(frames={"M1": _frame("M1", rows, vol=2.0)}, spread_points=10)
    sig = await Microstructure().evaluate(st)
    assert sig.vote == VOTE_SELL


async def test_microstructure_wide_spread_lowers_confidence() -> None:
    rows = [(2350 + i, 2351 + i, 2350.5 + i, 2350.8 + i) for i in range(10)]
    st = state(frames={"M1": _frame("M1", rows, vol=2.0)}, spread_points=80)
    sig = await Microstructure().evaluate(st)
    assert sig.confidence == 0.40


async def test_correlation_dxy_inverse() -> None:
    st = state(extra={"dxy_delta": -0.5})
    sig = await Correlation().evaluate(st)
    assert sig.vote == VOTE_BUY


async def test_correlation_yields_and_silver() -> None:
    st = state(extra={"yields_delta": 0.3, "silver_delta": -0.2})
    sig = await Correlation().evaluate(st)
    assert sig.vote == VOTE_SELL


async def test_correlation_no_data() -> None:
    sig = await Correlation().evaluate(state())
    assert sig.vote == VOTE_NEUTRAL


async def test_session_waterfall_bear_veto_buy() -> None:
    # 10 bars dropping by $1 each: total drop $10 (> $3.50), negative slope
    rows = [(2360 - i, 2360.5 - i, 2359 - i, 2359.2 - i) for i in range(10)]
    st = state(session="newyork", frames={"M15": _frame("M15", rows)})
    sig = await Session().evaluate(st)
    assert sig.vote == VOTE_SELL
    assert sig.veto == VETO_BUY
    assert sig.confidence >= 0.70
    assert sig.metadata["session_trend"] == "WATERFALL_BEAR"
    assert st.extra.get("session_waterfall_bear") is True


async def test_session_rocket_bull_veto_sell() -> None:
    # 10 bars rising by $1 each: total rise $10 (> $3.50), positive slope
    rows = [(2350 + i, 2351 + i, 2349.5 + i, 2350.8 + i) for i in range(10)]
    st = state(session="newyork", frames={"M15": _frame("M15", rows)})
    sig = await Session().evaluate(st)
    assert sig.vote == VOTE_BUY
    assert sig.veto == VETO_SELL
    assert sig.confidence >= 0.70
    assert sig.metadata["session_trend"] == "ROCKET_BULL"
    assert st.extra.get("session_waterfall_bull") is True


async def test_session_asia_range_ping_pong() -> None:
    # Tight range in Tokyo session oscillating between 2350 and 2353 (range $3)
    rows = [(2351, 2353, 2350, 2350.2) for _ in range(8)]
    st = state(session="tokyo", frames={"M15": _frame("M15", rows)})
    sig = await Session().evaluate(st)
    assert sig.metadata["session_trend"] == "ASIA_RANGE"
    assert st.extra.get("sideways_range") is True
    # At 2350.2, it is near session low -> buy defense vote + veto SELL
    assert sig.vote == VOTE_BUY
    assert sig.veto == VETO_SELL


async def test_liquidity_order_block_body_bounds() -> None:
    # 5 bars ending in a bullish order block expansion
    # Bar -2 is a red candle with long wicks: Open=2355, Close=2350, High=2358, Low=2345
    # Bar -1 is a strong green bar closing at 2360 (> 2358)
    rows = [
        (2348, 2350, 2347, 2349),
        (2349, 2351, 2348, 2350),
        (2350, 2352, 2349, 2351),
        (2355, 2358, 2345, 2350),  # Red candidate: Open=2355, Close=2350
        (2351, 2361, 2350, 2360),  # Expansion close at 2360 > High 2358
    ]
    st = state(frames={"M5": _frame("M5", rows)})
    sig = await Liquidity().evaluate(st)
    assert sig.vote == VOTE_BUY
    assert sig.metadata["order_block_bull"] is True
    # Crucial: Bounds are strictly [2350.0, 2355.0] (Body Only), NOT [2345.0, 2358.0] (Wicks Ignored)
    assert sig.metadata["ob_bull_body"] == (2350.0, 2355.0)


async def test_liquidity_order_block_retest() -> None:
    # Bar 2 is a red candle (Open=2352, Close=2348) followed by displacement up to 2365
    # Then bar 5 pulls back into the body zone [2348, 2352] (Low=2349, Close=2351)
    rows = [
        (2345, 2347, 2344, 2346),
        (2346, 2348, 2345, 2347),
        (2352, 2354, 2347, 2348),  # Red OB: body [2348, 2352]
        (2349, 2360, 2348, 2358),  # Displacement bar 1
        (2358, 2366, 2357, 2364),  # Displacement bar 2
        (2364, 2365, 2349, 2351),  # Retest: Low touches 2349 inside [2348, 2352], Close=2351
    ]
    st = state(frames={"M5": _frame("M5", rows)})
    sig = await Liquidity().evaluate(st)
    assert sig.vote == VOTE_BUY
    assert sig.metadata["ob_retest_bull"] is True
    assert sig.metadata["ob_bull_body"] == (2348.0, 2352.0)
    assert "retest" in sig.reasoning.lower()

