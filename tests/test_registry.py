"""Tests for the agent registry (Phase 1.4)."""

import pytest

from agents.base import DummyAgent
from agents.registry import AgentRegistry


def test_register_and_lookup() -> None:
    reg = AgentRegistry()
    a = DummyAgent("a1", division="timeframe")
    reg.register(a)
    assert reg.size == 1
    assert reg.get("a1") is a
    assert reg.weight("a1") == a.default_weight


def test_duplicate_registration_rejected() -> None:
    reg = AgentRegistry()
    reg.register(DummyAgent("a1"))
    with pytest.raises(ValueError):
        reg.register(DummyAgent("a1"))


def test_by_division_and_grouping() -> None:
    reg = AgentRegistry()
    reg.register_all([
        DummyAgent("t1", division="timeframe"),
        DummyAgent("t2", division="timeframe"),
        DummyAgent("r1", division="risk"),
    ])
    assert len(reg.by_division("timeframe")) == 2
    assert len(reg.by_division("risk")) == 1
    grouped = reg.divisions()
    assert set(grouped) == {"timeframe", "risk"}


def test_weight_override_and_load() -> None:
    reg = AgentRegistry()
    reg.register(DummyAgent("a1", weight=1.0))
    reg.set_weight("a1", 3.5)
    assert reg.weight("a1") == 3.5
    reg.set_weight("a1", -2.0)
    assert reg.weight("a1") == 0.0  # floored
    reg.load_weights({"a1": 2.0, "ghost": 9.0})
    assert reg.weight("a1") == 2.0
    assert reg.weight("ghost") == 1.0  # unknown never added


def test_clear() -> None:
    reg = AgentRegistry()
    reg.register(DummyAgent("a1"))
    reg.clear()
    assert reg.size == 0
