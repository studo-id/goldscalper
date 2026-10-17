"""Tests for the infra health agents (3 vote-neutral agents)."""

from __future__ import annotations

from agents.divisions.infra import (
    Connectivity,
    Heartbeat,
    Resource,
    build_infra_agents,
)
from agents.state import VOTE_NEUTRAL, SharedState


def state(**extra: object) -> SharedState:
    st = SharedState(symbol="XAUUSD")
    st.extra.update(extra)
    return st


def test_factory_returns_three() -> None:
    agents = build_infra_agents()
    assert {a.id for a in agents} == {
        "Infra-Heartbeat",
        "Infra-Connectivity",
        "Infra-Resource",
    }
    assert all(a.division == "infra" for a in agents)
    assert all(a.default_weight == 0.5 for a in agents)


async def test_all_infra_agents_vote_neutral() -> None:
    for agent in build_infra_agents():
        sig = await agent.evaluate(state())
        assert sig.vote == VOTE_NEUTRAL
        assert sig.confidence == 0.0


async def test_heartbeat_fresh() -> None:
    sig = await Heartbeat().evaluate(state(last_tick_age_s=1.0, last_candle_age_s=30.0))
    assert sig.metadata["healthy"] is True


async def test_heartbeat_stale() -> None:
    sig = await Heartbeat().evaluate(state(last_tick_age_s=30.0))
    assert sig.metadata["healthy"] is False
    assert sig.metadata["tick_stale"] is True


async def test_connectivity_healthy() -> None:
    sig = await Connectivity().evaluate(
        state(mt5_connected=True, redis_ok=True, db_ok=True)
    )
    assert sig.metadata["healthy"] is True


async def test_connectivity_degraded() -> None:
    sig = await Connectivity().evaluate(state(redis_ok=False))
    assert sig.metadata["healthy"] is False
    assert sig.metadata["redis"] is False


async def test_resource_healthy() -> None:
    sig = await Resource().evaluate(state(cycle_ms=40.0, error_count=0))
    assert sig.metadata["healthy"] is True


async def test_resource_over_budget() -> None:
    sig = await Resource().evaluate(state(cycle_ms=900.0, error_count=9))
    assert sig.metadata["healthy"] is False
    assert sig.metadata["latency_ok"] is False
    assert sig.metadata["errors_ok"] is False
