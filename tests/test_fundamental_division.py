"""Tests for the fundamental division (4 context agents)."""

from __future__ import annotations

from agents.divisions.fundamental import (
    Calendar,
    Intermarket,
    MacroRegime,
    NewsSentiment,
    build_fundamental_agents,
)
from agents.state import VETO_BUY, VOTE_BUY, VOTE_NEUTRAL, VOTE_SELL, SharedState


def state(**kw: object) -> SharedState:
    extra = kw.pop("extra", {})
    st = SharedState(symbol="XAUUSD", **kw)  # type: ignore[arg-type]
    if isinstance(extra, dict):
        st.extra.update(extra)
    return st


def test_factory_returns_four() -> None:
    agents = build_fundamental_agents()
    assert {a.id for a in agents} == {
        "Fund-Calendar",
        "Fund-NewsSentiment",
        "Fund-MacroRegime",
        "Fund-Intermarket",
    }
    assert all(a.division == "fundamental" for a in agents)
    assert all(a.default_weight == 0.8 for a in agents)


async def test_calendar_reports_blackout() -> None:
    st = state(extra={"news_blackout": True, "calendar_events": [{"impact": "high"}]})
    sig = await Calendar().evaluate(st)
    assert sig.vote == VOTE_NEUTRAL
    assert sig.veto == VETO_BUY
    assert sig.metadata["blackout"] is True
    assert sig.metadata["high_impact"] == 1


async def test_news_sentiment_positive() -> None:
    sig = await NewsSentiment().evaluate(state(extra={"news_sentiment": 0.6}))
    assert sig.vote == VOTE_BUY


async def test_news_sentiment_negative() -> None:
    sig = await NewsSentiment().evaluate(state(extra={"news_sentiment": -0.5}))
    assert sig.vote == VOTE_SELL


async def test_news_sentiment_absent() -> None:
    sig = await NewsSentiment().evaluate(state())
    assert sig.vote == VOTE_NEUTRAL


async def test_macro_dovish() -> None:
    sig = await MacroRegime().evaluate(state(extra={"macro_bias": "dovish"}))
    assert sig.vote == VOTE_BUY


async def test_macro_hawkish() -> None:
    sig = await MacroRegime().evaluate(state(extra={"macro_bias": "hawkish"}))
    assert sig.vote == VOTE_SELL


async def test_macro_score_fallback() -> None:
    sig = await MacroRegime().evaluate(state(extra={"macro_score": 0.4}))
    assert sig.vote == VOTE_BUY


async def test_macro_absent() -> None:
    sig = await MacroRegime().evaluate(state())
    assert sig.vote == VOTE_NEUTRAL


async def test_intermarket_dxy_inverse() -> None:
    sig = await Intermarket().evaluate(state(extra={"dxy_delta": -0.5}))
    assert sig.vote == VOTE_BUY


async def test_intermarket_yields_and_equities() -> None:
    sig = await Intermarket().evaluate(state(extra={"us10y_delta": 0.3, "spx_delta": -0.4}))
    assert sig.vote == VOTE_SELL


async def test_intermarket_absent() -> None:
    sig = await Intermarket().evaluate(state())
    assert sig.vote == VOTE_NEUTRAL
