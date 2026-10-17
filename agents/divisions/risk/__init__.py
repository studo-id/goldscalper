"""Risk division — capital protection and scalper economics (6 agents)."""

from __future__ import annotations

from agents.divisions.risk.agents import (
    RISK_AGENT_CLASSES,
    CostMonitor,
    DrawdownGuard,
    EntryTiming,
    PositionSizer,
    StopLoss,
    TakeProfit,
    proposed_stop_distance,
    round_to_step,
)
from agents.divisions.risk.base import ATR_TIMEFRAMES, DIVISION, RISK_WEIGHT, RiskAgent
from config.settings import Settings
from config.settings import settings as default_settings

__all__ = [
    "DIVISION",
    "RISK_WEIGHT",
    "ATR_TIMEFRAMES",
    "RiskAgent",
    "PositionSizer",
    "StopLoss",
    "TakeProfit",
    "EntryTiming",
    "DrawdownGuard",
    "CostMonitor",
    "RISK_AGENT_CLASSES",
    "round_to_step",
    "proposed_stop_distance",
    "build_risk_agents",
]


def build_risk_agents(settings: Settings | None = None) -> list[RiskAgent]:
    """Instantiate the six risk-division agents sharing one settings object."""
    s = settings or default_settings
    return [cls(settings=s) for cls in RISK_AGENT_CLASSES]
