"""Tests for the timeframe division (7 scouts + synthetic DXY)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agents.divisions.timeframe import (
    D1Macro,
    H1Regime,
    H4Structure,
    M1Sniper,
    M5Inspector,
    M15Liquidity,
    M30Momentum,
    SyntheticDXYAgent,
    build_timeframe_agents,
    calculate_synthetic_dxy,
    evaluate_macro_sentiment,
)
from agents.divisions.timeframe.base import HTF_WEIGHT, LTF_WEIGHT
from agents.state import (
    VETO_BUY,
    VETO_SELL,
    VOTE_BUY,
    VOTE_NEUTRAL,
    VOTE_SELL,
    SharedState,
)
from core.market_data import Candle, tf_seconds
from spk.decision import ACTION_BUY
from spk.veto import evaluate as veto_evaluate

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)

Rows = list[tuple[float, float, float, float]]


def frame(tf: str, rows: Rows) -> list[Candle]:
    step = tf_seconds(tf)
    return [
        Candle("XAUUSD", tf, BASE + timedelta(seconds=step * i), o, h, low, c)
        for i, (o, h, low, c) in enumerate(rows)
    ]


def state(frames: dict[str, list[Candle]], **extra: object) -> SharedState:
    return SharedState(symbol="XAUUSD", frames=frames, extra=dict(extra))


_RISING: Rows = [(2350 + i, 2351 + i, 2349 + i, 2350.5 + i) for i in range(10)]
_FALLING: Rows = [(2360 - i, 2361 - i, 2359 - i, 2359.5 - i) for i in range(10)]


# --- factory -------------------------------------------------------------------


def test_factory_returns_all_agents() -> None:
    agents = build_timeframe_agents()
    ids = {a.id for a in agents}
    assert ids == {
        "TF-M1-Sniper",
        "TF-M5-Inspector",
        "TF-M15-Liquidity",
        "TF-M30-Momentum",
        "TF-H1-Regime",
        "TF-H4-Structure",
        "TF-D1-Macro",
        "TF-DXY-Synthetic",
    }
    assert all(a.division == "timeframe" for a in agents)


def test_division_weights_follow_blueprint() -> None:
    by_id = {a.id: a for a in build_timeframe_agents()}
    for agent_id in ("TF-H1-Regime", "TF-H4-Structure", "TF-D1-Macro"):
        assert by_id[agent_id].default_weight == HTF_WEIGHT == 1.5
    for agent_id in (
        "TF-M1-Sniper",
        "TF-M5-Inspector",
        "TF-M15-Liquidity",
        "TF-M30-Momentum",
        "TF-DXY-Synthetic",
    ):
        assert by_id[agent_id].default_weight == LTF_WEIGHT == 1.2


# --- M1 sniper -----------------------------------------------------------------


async def test_m1_bearish_rejection() -> None:
    st = state({"M1": frame("M1", [(2350, 2350.5, 2349.5, 2350.0), (2350, 2351, 2349.4, 2349.5)])})
    sig = await M1Sniper().evaluate(st)
    assert sig.vote == VOTE_SELL
    assert sig.metadata["rejection"] == "BEARISH_REJECTION"
    assert sig.confidence == 0.75


async def test_m1_bullish_rejection() -> None:
    rows: Rows = [(2350, 2350.5, 2349.5, 2350.0), (2350, 2350.6, 2349.0, 2350.5)]
    sig = await M1Sniper().evaluate(state({"M1": frame("M1", rows)}))
    assert sig.vote == VOTE_BUY
    assert sig.metadata["rejection"] == "BULLISH_REJECTION"


async def test_m1_insufficient_data_is_neutral() -> None:
    sig = await M1Sniper().evaluate(state({"M1": frame("M1", [(2350, 2350, 2350, 2350)])}))
    assert sig.vote == VOTE_NEUTRAL


# --- M5 inspector --------------------------------------------------------------


async def test_m5_displacement_bullish() -> None:
    small: Rows = [(2350, 2350.1, 2349.9, 2350.0) for _ in range(14)]
    rows = [*small, (2350, 2353.5, 2349.9, 2353.0)]
    sig = await M5Inspector().evaluate(state({"M5": frame("M5", rows)}))
    assert sig.vote == VOTE_BUY
    assert sig.metadata["displacement"] is True
    assert sig.confidence == 0.80


# --- M15 liquidity -------------------------------------------------------------


async def test_m15_bullish_trend() -> None:
    sig = await M15Liquidity().evaluate(state({"M15": frame("M15", _RISING)}))
    assert sig.vote == VOTE_BUY
    assert sig.metadata["bsl_pool"] >= sig.metadata["close"] - 1.5


# --- M30 momentum --------------------------------------------------------------


async def test_m30_bearish_exhaustion() -> None:
    bar = (2350, 2351, 2349.8, 2349.9)
    sig = await M30Momentum().evaluate(state({"M30": frame("M30", [bar, bar, bar])}))
    assert sig.vote == VOTE_SELL
    assert sig.metadata["exhaustion"] == "BEARISH_EXHAUSTION"


async def test_m30_bullish_exhaustion() -> None:
    bar = (2350, 2350.2, 2349, 2350.1)
    sig = await M30Momentum().evaluate(state({"M30": frame("M30", [bar, bar, bar])}))
    assert sig.vote == VOTE_BUY
    assert sig.metadata["exhaustion"] == "BULLISH_EXHAUSTION"


# --- H1 regime (veto) ----------------------------------------------------------


async def test_h1_trending_bullish_vetoes_sell() -> None:
    sig = await H1Regime().evaluate(state({"H1": frame("H1", _RISING)}))
    assert sig.vote == VOTE_BUY
    assert sig.metadata["regime"] == "TRENDING"
    assert sig.veto == VETO_SELL


async def test_h1_trending_bearish_vetoes_buy() -> None:
    sig = await H1Regime().evaluate(state({"H1": frame("H1", _FALLING)}))
    assert sig.vote == VOTE_SELL
    assert sig.veto == VETO_BUY


async def test_h1_sideways_at_top_vetoes_buy() -> None:
    rows: Rows = [
        (2350, 2352, 2349, 2351),
        (2351, 2352, 2349, 2350),
        (2350, 2352, 2349, 2351),
        (2351, 2352, 2349, 2350),
        (2350, 2352, 2349, 2351),
        (2351, 2352, 2349, 2350),
        (2350, 2352, 2349, 2351),
        (2351, 2352, 2349, 2351.9),
    ]
    sig = await H1Regime().evaluate(state({"H1": frame("H1", rows)}))
    assert sig.metadata["regime"] == "SIDEWAYS"
    assert sig.vote == VOTE_SELL
    assert sig.veto == VETO_BUY


# --- H4 structure (veto) -------------------------------------------------------


async def test_h4_supply_touch_vetoes_buy() -> None:
    sig = await H4Structure().evaluate(state({"H4": frame("H4", _RISING)}))
    assert sig.veto == VETO_BUY
    assert sig.vote == VOTE_BUY


async def test_h4_demand_touch_vetoes_sell() -> None:
    sig = await H4Structure().evaluate(state({"H4": frame("H4", _FALLING)}))
    assert sig.veto == VETO_SELL


# --- D1 macro (veto) -----------------------------------------------------------


async def test_d1_extreme_premium_vetoes_buy() -> None:
    rows: Rows = [(2350, 2360, 2340, 2350), (2355, 2361, 2354, 2359)]
    sig = await D1Macro().evaluate(state({"D1": frame("D1", rows)}))
    assert sig.metadata["zone"] == "EXTREME_PREMIUM"
    assert sig.veto == VETO_BUY
    assert sig.vote == VOTE_BUY


async def test_d1_extreme_discount_vetoes_sell() -> None:
    rows: Rows = [(2350, 2360, 2340, 2350), (2345, 2346, 2339, 2341)]
    sig = await D1Macro().evaluate(state({"D1": frame("D1", rows)}))
    assert sig.metadata["zone"] == "EXTREME_DISCOUNT"
    assert sig.veto == VETO_SELL


async def test_d1_macro_bullish_vetoes_sell() -> None:
    # 5 rising D1 candles, ending at 2352 inside normal PREMIUM (range 2330-2360, not extreme)
    rows: Rows = [
        (2335, 2345, 2330, 2340),
        (2340, 2350, 2335, 2345),
        (2345, 2355, 2340, 2348),
        (2348, 2360, 2345, 2350),
        (2350, 2356, 2348, 2352),
    ]
    sig = await D1Macro().evaluate(state({"D1": frame("D1", rows)}))
    assert sig.vote == VOTE_BUY
    assert sig.metadata["bias"] == "BULLISH"
    assert sig.metadata["zone"] == "PREMIUM"
    assert sig.veto == VETO_SELL


async def test_d1_macro_bearish_vetoes_buy() -> None:
    # 5 falling D1 candles, ending at 2338 inside normal DISCOUNT (range 2330-2360, not extreme)
    rows: Rows = [
        (2355, 2360, 2350, 2352),
        (2352, 2355, 2345, 2348),
        (2348, 2350, 2340, 2344),
        (2344, 2348, 2335, 2340),
        (2340, 2342, 2334, 2338),
    ]
    sig = await D1Macro().evaluate(state({"D1": frame("D1", rows)}))
    assert sig.vote == VOTE_SELL
    assert sig.metadata["bias"] == "BEARISH"
    assert sig.metadata["zone"] == "DISCOUNT"
    assert sig.veto == VETO_BUY


# --- synthetic DXY factor ------------------------------------------------------


def test_calculate_synthetic_dxy_guards() -> None:
    assert calculate_synthetic_dxy(0, 150, 1.27) == 103.0
    assert 80.0 < calculate_synthetic_dxy(1.10, 150.0, 1.27) < 120.0


def test_macro_sentiment_bearish_usd_is_gold_bullish() -> None:
    sentiment = evaluate_macro_sentiment(102.0, dxy_baseline=102.5, vix_current=25.0)
    assert sentiment["gold_macro_bias"] == "BULLISH"
    assert sentiment["risk_mode"] == "RISK_OFF"
    assert sentiment["score_modifier"] > 0


async def test_dxy_agent_votes_buy_on_weak_dollar() -> None:
    dxy = calculate_synthetic_dxy(1.10, 150.0, 1.27)
    st = state({}, eurusd=1.10, usdjpy=150.0, gbpusd=1.27, dxy_baseline=dxy + 0.3)
    sig = await SyntheticDXYAgent().evaluate(st)
    assert sig.vote == VOTE_BUY
    assert sig.timeframe is None


async def test_dxy_agent_neutral_without_inputs() -> None:
    sig = await SyntheticDXYAgent().evaluate(state({}))
    assert sig.vote == VOTE_NEUTRAL
    assert sig.confidence == 0.0


# --- integration: scout veto blocks the SPK trade ------------------------------


async def test_h1_veto_blocks_buy_via_spk() -> None:
    st = state({"H1": frame("H1", _FALLING)})
    h1 = await H1Regime().evaluate(st)
    m5_rows: Rows = [(2350, 2353.5, 2349.9, 2353.0)]
    sell = await M5Inspector().evaluate(state({"M5": frame("M5", m5_rows)}))

    result = veto_evaluate([h1, sell], st, ACTION_BUY)
    assert result.hard is True
    assert "blocked" in (result.reason or "")


async def test_d1_extreme_zone_blocks_buy_via_spk() -> None:
    rows: Rows = [(2350, 2360, 2340, 2350), (2355, 2361, 2354, 2359)]
    st = state({"D1": frame("D1", rows)})
    d1 = await D1Macro().evaluate(st)
    result = veto_evaluate([d1], st, ACTION_BUY)
    assert result.hard is True
