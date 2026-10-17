"""Timeframe division — the 7-Scouts Boardroom plus the synthetic DXY factor."""

from __future__ import annotations

from agents.divisions.timeframe.base import (
    DIVISION,
    HTF_WEIGHT,
    LTF_WEIGHT,
    Bars,
    TimeframeAgent,
)
from agents.divisions.timeframe.dxy import (
    SyntheticDXYAgent,
    calculate_synthetic_dxy,
    evaluate_macro_sentiment,
)
from agents.divisions.timeframe.scouts import (
    SCOUT_CLASSES,
    D1Macro,
    H1Regime,
    H4Structure,
    M1Sniper,
    M5Inspector,
    M15Liquidity,
    M30Momentum,
)

__all__ = [
    "DIVISION",
    "HTF_WEIGHT",
    "LTF_WEIGHT",
    "Bars",
    "TimeframeAgent",
    "M1Sniper",
    "M5Inspector",
    "M15Liquidity",
    "M30Momentum",
    "H1Regime",
    "H4Structure",
    "D1Macro",
    "SCOUT_CLASSES",
    "SyntheticDXYAgent",
    "calculate_synthetic_dxy",
    "evaluate_macro_sentiment",
    "build_timeframe_agents",
]


def build_timeframe_agents(include_dxy: bool = True) -> list[TimeframeAgent]:
    """Instantiate the timeframe division's agents (7 scouts + optional DXY)."""
    agents: list[TimeframeAgent] = [cls() for cls in SCOUT_CLASSES]
    if include_dxy:
        agents.append(SyntheticDXYAgent())
    return agents
