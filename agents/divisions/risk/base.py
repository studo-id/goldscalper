"""Base class for risk-division agents.

Risk agents are **vote-neutral** (they never cast a directional vote). Instead
they attach risk *parameters* (size, SL/TP distances, timing, costs) and *guards*
(halts) that the pre-trade :mod:`execution.risk_gate` reads, re-validates, and
stamps onto the final :class:`~spk.decision.SPKDecision`.
"""

from __future__ import annotations

from typing import Any

from agents.base import AgentSignal, BaseAgent
from agents.state import VOTE_NEUTRAL, SharedState
from config.logging import get_logger
from core.indicators import atr
from core.market_data import TIMEFRAMES, Bars

log = get_logger("agents.risk")

# BLUEPRINT §5.2 — capital protection is paramount.
RISK_WEIGHT = 2.0
DIVISION = "risk"

# Preferred order for locating an ATR series.
ATR_TIMEFRAMES = ("M5", "M15", "M1", "M30", "H1", "H4", "D1")


def estimate_atr(
    state: SharedState,
    period: int = 14,
    timeframes: tuple[str, ...] = ATR_TIMEFRAMES,
    default: float = 1.0,
) -> tuple[float, str | None]:
    """Return ``(atr, timeframe)`` using the first available timeframe series."""
    for tf in timeframes:
        if tf not in TIMEFRAMES:
            continue
        bars = Bars.for_timeframe(state, tf)
        if bars.n >= 2:
            return atr(bars.highs, bars.lows, bars.closes, period=period, default=default), tf
    return default, None


class RiskAgent(BaseAgent):
    """Vote-neutral risk agent emitting parameters/guards via metadata."""

    division = DIVISION

    def __init__(self) -> None:
        super().__init__()
        self.division = DIVISION
        self.default_weight = RISK_WEIGHT

    def emit(
        self,
        reasoning: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentSignal:
        """Build a neutral signal carrying risk metadata."""
        return AgentSignal(
            agent_id=self.id,
            division=self.division,
            vote=VOTE_NEUTRAL,
            confidence=0.0,
            weight=self.default_weight,
            reasoning=reasoning,
            metadata=metadata or {},
        )


__all__ = ["RISK_WEIGHT", "DIVISION", "RiskAgent", "estimate_atr", "ATR_TIMEFRAMES"]
