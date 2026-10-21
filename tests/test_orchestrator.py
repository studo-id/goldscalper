"""Tests for the orchestrator decision loop (Phase 1.8)."""

from agents.base import DummyAgent
from agents.message_bus import MemoryBus
from agents.orchestrator import Orchestrator
from agents.registry import AgentRegistry
from agents.state import VETO_BUY, VOTE_BUY, VOTE_NEUTRAL, VOTE_SELL, SharedState
from spk.decision import ACTION_BUY, ACTION_HOLD, ACTION_SELL


def _registry(*agents: DummyAgent) -> AgentRegistry:
    reg = AgentRegistry()
    reg.register_all(list(agents))
    return reg


async def test_consensus_buy() -> None:
    reg = _registry(
        DummyAgent("a1", division="timeframe", vote=VOTE_BUY, confidence=0.9, weight=1.5),
        DummyAgent("a2", division="risk", vote=VOTE_BUY, confidence=0.9, weight=2.0),
    )
    orch = Orchestrator(reg, bus=MemoryBus(), broadcast=False)
    decision = await orch.run_cycle()
    assert decision.action == ACTION_BUY
    assert decision.hard_veto is False
    assert decision.tradable is True
    assert decision.participation == 2


async def test_consensus_sell() -> None:
    reg = _registry(
        DummyAgent("a1", division="timeframe", vote=VOTE_SELL, confidence=0.9, weight=1.5),
        DummyAgent("a2", division="risk", vote=VOTE_SELL, confidence=0.9, weight=2.0),
    )
    orch = Orchestrator(reg, bus=MemoryBus(), broadcast=False)
    decision = await orch.run_cycle()
    assert decision.action == ACTION_SELL
    assert decision.tradable is True


async def test_balanced_is_hold() -> None:
    reg = _registry(
        DummyAgent("b1", division="timeframe", vote=VOTE_BUY, confidence=0.5),
        DummyAgent("b2", division="structure", vote=VOTE_SELL, confidence=0.5),
    )
    orch = Orchestrator(reg, bus=MemoryBus(), broadcast=False)
    decision = await orch.run_cycle()
    assert decision.action == ACTION_HOLD
    assert decision.tradable is False


async def test_hard_veto_makes_untradable() -> None:
    reg = _registry(
        DummyAgent("c1", division="risk", vote=VOTE_BUY, confidence=1.0, weight=2.0),
        DummyAgent("c2", division="risk", vote=VOTE_NEUTRAL, confidence=1.0, veto=VETO_BUY),
    )
    orch = Orchestrator(reg, bus=MemoryBus(), broadcast=False)
    decision = await orch.run_cycle()
    assert decision.action == ACTION_BUY
    assert decision.hard_veto is True
    assert decision.tradable is False
    assert decision.veto_reason is not None


async def test_publishes_spk_event() -> None:
    bus = MemoryBus()
    reg = _registry(DummyAgent("d1", division="risk", vote=VOTE_BUY, confidence=1.0, weight=2.0))
    orch = Orchestrator(reg, bus=bus, broadcast=False)
    await orch.run_cycle()
    msgs = bus.messages("gs:spk")
    assert len(msgs) == 1
    assert msgs[0]["action"] == ACTION_BUY


async def test_soft_veto_reduces_confidence() -> None:
    reg = _registry(
        DummyAgent("e1", division="risk", vote=VOTE_BUY, confidence=0.6, weight=2.0)
    )

    def _state() -> SharedState:
        return SharedState(spread_points=100, session="asia", extra={"h1_vote": -1})

    orch = Orchestrator(reg, bus=MemoryBus(), state_builder=_state, broadcast=False)
    decision = await orch.run_cycle()
    assert decision.action == ACTION_BUY
    assert decision.soft_notes
    assert decision.confidence < 0.5


async def test_start_and_stop() -> None:
    import asyncio

    from config.settings import settings as base_settings

    reg = _registry(DummyAgent("f1", division="risk", vote=VOTE_BUY, confidence=1.0, weight=2.0))
    fast = base_settings.model_copy(update={"cycle_interval_ms": 10})
    orch = Orchestrator(reg, settings=fast, bus=MemoryBus(), broadcast=False)
    task = orch.start()
    await asyncio.sleep(0.05)
    await orch.stop()
    assert task.done()
    assert orch.cycle_count >= 1


async def test_low_confidence_gets_hard_veto() -> None:
    # High enough weight for SPK BUY action, but soft veto drops confidence below 0.40
    reg = _registry(
        DummyAgent("low1", division="trend", vote=VOTE_BUY, confidence=0.55, weight=3.0)
    )

    def _state() -> SharedState:
        return SharedState(spread_points=100, session="asia", extra={"h1_vote": -1})

    orch = Orchestrator(reg, bus=MemoryBus(), state_builder=_state, broadcast=False)
    decision = await orch.run_cycle()
    assert decision.action == ACTION_BUY
    assert decision.confidence < 0.40
    assert decision.hard_veto is True
    assert decision.veto_reason is not None and "LOW CONFIDENCE" in decision.veto_reason


async def test_defense_mode_min_confidence_floor() -> None:
    # In DEFENSE mode (daily_pnl_pct < 0), confidence below 0.50 is strictly vetoed
    reg = _registry(
        DummyAgent("def1", division="trend", vote=VOTE_BUY, confidence=0.55, weight=3.0),
    )

    def _state() -> SharedState:
        return SharedState(spread_points=100, session="asia", daily_pnl_pct=-2.0, extra={"remaining_target_usd": 50.0, "h1_vote": -1})

    orch = Orchestrator(reg, bus=MemoryBus(), state_builder=_state, broadcast=False)
    decision = await orch.run_cycle()
    assert decision.action == ACTION_BUY
    assert decision.confidence < 0.50
    assert decision.hard_veto is True
    assert "DEFENSE mode" in (decision.veto_reason or "")


async def test_wave_chain_3_pucuk_guard() -> None:
    # When wave has reached Chain #3+ (chain_count >= 2), confidence < 0.60 is blocked
    reg = _registry(
        DummyAgent("wave1", division="trend", vote=VOTE_BUY, confidence=0.50, weight=2.0),
        DummyAgent("wave2", division="technical", vote=VOTE_SELL, confidence=0.30, weight=1.0),
    )

    def _state() -> SharedState:
        return SharedState(
            spread_points=100,
            daily_pnl_pct=1.0,
            extra={"remaining_target_usd": 50.0, "h1_vote": -1, "wave_capacity": {"chain_count": 2}},
        )

    orch = Orchestrator(reg, bus=MemoryBus(), state_builder=_state, broadcast=False)
    decision = await orch.run_cycle()
    assert decision.action == ACTION_BUY
    assert decision.confidence < 0.60
    assert decision.hard_veto is True
    assert "CHAIN_3 mode" in (decision.veto_reason or "")


