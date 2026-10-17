"""Technical division — classical indicator confirmation (6 agents)."""

from __future__ import annotations

from agents.divisions.technical.agents import (
    TECHNICAL_AGENT_CLASSES,
    Momentum,
    Pattern,
    SupportResistance,
    Trend,
    Volatility,
    Volume,
)
from agents.divisions.technical.base import DIVISION, TECHNICAL_WEIGHT, TechnicalAgent

__all__ = [
    "DIVISION",
    "TECHNICAL_WEIGHT",
    "TechnicalAgent",
    "Trend",
    "Momentum",
    "Volatility",
    "Volume",
    "SupportResistance",
    "Pattern",
    "TECHNICAL_AGENT_CLASSES",
    "build_technical_agents",
]


def build_technical_agents() -> list[TechnicalAgent]:
    """Instantiate the six technical-division agents."""
    return [cls() for cls in TECHNICAL_AGENT_CLASSES]
