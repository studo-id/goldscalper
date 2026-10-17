"""Tests for the SPK-core meta-agents (5 vote-neutral observers)."""

from __future__ import annotations

from agents.divisions.spk_core import (
    Aggregator,
    Chief,
    Confidence,
    Resolver,
    Tracker,
    build_spk_core_agents,
)
from agents.state import VOTE_NEUTRAL, SharedState


def state(**extra: object) -> SharedState:
    st = SharedState(symbol="XAUUSD")
    st.extra.update(extra)
    return st


def test_factory_returns_five() -> None:
    agents = build_spk_core_agents()
    assert {a.id for a in agents} == {
        "SPK-Chief",
        "SPK-Aggregator",
        "SPK-Resolver",
        "SPK-Confidence",
        "SPK-Tracker",
    }
    assert all(a.division == "spk_core" for a in agents)
    assert all(a.default_weight == 1.5 for a in agents)


async def test_all_spk_agents_vote_neutral() -> None:
    st = state(action="BUY", score=3.0, division_scores={"timeframe": 2.0})
    for agent in build_spk_core_agents():
        sig = await agent.evaluate(st)
        assert sig.vote == VOTE_NEUTRAL
        assert sig.confidence == 0.0


async def test_chief_go() -> None:
    sig = await Chief().evaluate(state(action="BUY", score=3.0, hard_veto=False))
    assert sig.metadata["go"] is True
    assert sig.metadata["sizing_authority"] is True


async def test_chief_no_go_on_veto() -> None:
    sig = await Chief().evaluate(state(action="BUY", score=3.0, hard_veto=True))
    assert sig.metadata["go"] is False


async def test_chief_no_go_on_hold() -> None:
    sig = await Chief().evaluate(state(action="HOLD"))
    assert sig.metadata["go"] is False


async def test_aggregator_summarises_divisions() -> None:
    st = state(division_scores={"timeframe": 2.5, "risk": 0.0, "technical": -0.5})
    sig = await Aggregator().evaluate(st)
    assert sig.metadata["net"] == 2.0
    assert sig.metadata["dominant_division"] == "timeframe"


async def test_aggregator_empty() -> None:
    sig = await Aggregator().evaluate(state())
    assert sig.metadata["divisions"] == 0


async def test_resolver_detects_conflict() -> None:
    sig = await Resolver().evaluate(state(htf_vote=-1, ltf_vote=1))
    assert sig.metadata["conflict"] is True
    assert sig.metadata["resolution"] == "higher_timeframe_priority"


async def test_resolver_aligned() -> None:
    sig = await Resolver().evaluate(state(htf_vote=1, ltf_vote=1))
    assert sig.metadata["conflict"] is False


async def test_confidence_probability() -> None:
    sig = await Confidence().evaluate(state(score=2.0, participation=0.8))
    assert 0.5 < sig.metadata["probability"] < 1.0


async def test_confidence_absent() -> None:
    sig = await Confidence().evaluate(state())
    assert "probability" not in sig.metadata


async def test_tracker_leaderboard() -> None:
    st = state(agent_winrates={"TF-M1-Sniper": 0.7, "Tech-RSI": 0.4, "Risk-PositionSizer": 0.55})
    sig = await Tracker().evaluate(st)
    assert sig.metadata["best_agent"] == "TF-M1-Sniper"
    assert sig.metadata["worst_agent"] == "Tech-RSI"
