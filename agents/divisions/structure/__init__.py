"""Structure division — liquidity, session, and order-flow edge (5 agents)."""

from __future__ import annotations

from agents.divisions.structure.agents import (
    STRUCTURE_AGENT_CLASSES,
    Correlation,
    Liquidity,
    MarketStructure,
    Microstructure,
    Session,
)
from agents.divisions.structure.base import DIVISION, STRUCTURE_WEIGHT, StructureAgent

__all__ = [
    "DIVISION",
    "STRUCTURE_WEIGHT",
    "StructureAgent",
    "MarketStructure",
    "Liquidity",
    "Session",
    "Microstructure",
    "Correlation",
    "STRUCTURE_AGENT_CLASSES",
    "build_structure_agents",
]


def build_structure_agents() -> list[StructureAgent]:
    """Instantiate the five structure-division agents."""
    return [cls() for cls in STRUCTURE_AGENT_CLASSES]
