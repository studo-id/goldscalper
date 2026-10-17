"""Tests for the base agent contract (Phase 1.9)."""

from agents.base import AgentSignal, BaseAgent, DummyAgent
from agents.message_bus import MemoryBus
from agents.state import VETO_BUY, VOTE_BUY, VOTE_NEUTRAL, VOTE_SELL, SharedState


def test_signal_clamps_values() -> None:
    sig = AgentSignal(agent_id="a", division="d", vote=5, confidence=2.0, weight=-1)
    assert sig.vote == 1
    assert sig.confidence == 1.0
    assert sig.weight == 0.0


def test_signal_score() -> None:
    sig = AgentSignal(agent_id="a", division="d", vote=VOTE_BUY, confidence=0.5, weight=2.0)
    assert sig.score == 1.0
    neg = AgentSignal(agent_id="b", division="d", vote=VOTE_SELL, confidence=0.5, weight=2.0)
    assert neg.score == -1.0


async def test_run_cycle_returns_signal() -> None:
    agent = DummyAgent("t1", vote=VOTE_BUY, confidence=0.8, weight=1.5)
    sig = await agent.run_cycle(SharedState())
    assert sig.agent_id == "t1"
    assert sig.vote == VOTE_BUY
    assert sig.weight == 1.5
    assert sig.latency_ms >= 0.0
    assert agent.last_signal is sig


async def test_run_cycle_applies_registry_weight() -> None:
    agent = DummyAgent("t2", vote=VOTE_BUY, confidence=0.5, weight=1.0)
    sig = await agent.run_cycle(SharedState(), weight=2.5)
    assert sig.weight == 2.5


async def test_error_is_contained() -> None:
    agent = DummyAgent("boom", raise_error=True)
    sig = await agent.run_cycle(SharedState())
    assert sig.vote == VOTE_NEUTRAL
    assert sig.confidence == 0.0
    assert "error:" in sig.reasoning
    assert agent.error_count == 1


async def test_publishes_to_bus() -> None:
    bus = MemoryBus()
    agent = DummyAgent("t3", vote=VOTE_SELL, confidence=0.4)
    await agent.run_cycle(SharedState(), bus=bus, stream="gs:signals")
    msgs = bus.messages("gs:signals")
    assert len(msgs) == 1
    assert msgs[0]["agent_id"] == "t3"
    assert msgs[0]["vote"] == VOTE_SELL


async def test_veto_flag_propagates() -> None:
    agent = DummyAgent("vetoer", veto=VETO_BUY)
    sig = await agent.run_cycle(SharedState())
    assert sig.veto == VETO_BUY


def test_base_agent_is_abstract() -> None:
    try:
        BaseAgent()  # type: ignore[abstract]
    except TypeError:
        return
    raise AssertionError("BaseAgent should not be instantiable")
