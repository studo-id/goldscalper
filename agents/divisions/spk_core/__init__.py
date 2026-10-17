"""SPK-core division — vote-neutral meta-agents (5 agents)."""

from __future__ import annotations

from agents.divisions.spk_core.agents import (
    SPK_CORE_AGENT_CLASSES,
    Aggregator,
    Chief,
    Confidence,
    Resolver,
    Tracker,
)
from agents.divisions.spk_core.base import DIVISION, SPK_CORE_WEIGHT, SPKCoreAgent

__all__ = [
    "DIVISION",
    "SPK_CORE_WEIGHT",
    "SPKCoreAgent",
    "Chief",
    "Aggregator",
    "Resolver",
    "Confidence",
    "Tracker",
    "SPK_CORE_AGENT_CLASSES",
    "build_spk_core_agents",
]


def build_spk_core_agents() -> list[SPKCoreAgent]:
    """Instantiate the five SPK-core meta-agents."""
    return [cls() for cls in SPK_CORE_AGENT_CLASSES]
