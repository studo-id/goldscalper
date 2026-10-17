"""Tests for the full division roster assembly."""

from __future__ import annotations

from agents.divisions import build_all_agents
from agents.registry import AgentRegistry


def test_build_all_agents_count() -> None:
    agents = build_all_agents()
    assert len(agents) == 37  # 8 timeframe (incl. DXY) + 29 others


def test_build_all_agents_ids_unique() -> None:
    agents = build_all_agents()
    ids = [a.id for a in agents]
    assert len(ids) == len(set(ids))


def test_build_all_agents_without_dxy() -> None:
    agents = build_all_agents(include_dxy=False)
    assert len(agents) == 36


def test_registry_accepts_full_roster() -> None:
    registry = AgentRegistry()
    registry.register_all(build_all_agents())
    assert registry.size == 37
