"""Fundamental division — news / macro / intermarket filter (4 agents)."""

from __future__ import annotations

from agents.divisions.fundamental.agents import (
    FUNDAMENTAL_AGENT_CLASSES,
    Calendar,
    Intermarket,
    MacroRegime,
    NewsSentiment,
)
from agents.divisions.fundamental.base import (
    DIVISION,
    FUNDAMENTAL_WEIGHT,
    FundamentalAgent,
)

__all__ = [
    "DIVISION",
    "FUNDAMENTAL_WEIGHT",
    "FundamentalAgent",
    "Calendar",
    "NewsSentiment",
    "MacroRegime",
    "Intermarket",
    "FUNDAMENTAL_AGENT_CLASSES",
    "build_fundamental_agents",
]


def build_fundamental_agents() -> list[FundamentalAgent]:
    """Instantiate the four fundamental-division agents."""
    return [cls() for cls in FUNDAMENTAL_AGENT_CLASSES]
