"""Base class for technical-division agents.

Technical agents are **directional voters** driven by indicator maths
(EMA/RSI/MACD/Bollinger/volume/ADX) over OHLC frames.
"""

from __future__ import annotations

from typing import Any

from agents.base import AgentSignal, BaseAgent
from agents.state import VOTE_NEUTRAL, SharedState
from config.logging import get_logger
from core.market_data import Bars

log = get_logger("agents.technical")

# BLUEPRINT §5.2 — classical indicator confirmation.
TECHNICAL_WEIGHT = 1.0
DIVISION = "technical"


class TechnicalAgent(BaseAgent):
    """Base technical agent: resolves bars and shapes signals."""

    division = DIVISION
    timeframe: str | None = "M15"
    min_bars = 3

    def __init__(self) -> None:
        super().__init__()
        self.division = DIVISION
        self.default_weight = TECHNICAL_WEIGHT

    def bars(self, state: SharedState, timeframe: str | None = None) -> Bars:
        tf = timeframe or self.timeframe or ""
        b = Bars.for_timeframe(state, tf)
        if b.n == 0 and tf == "M5" and "M15" in (state.frames or {}):
            return Bars.for_timeframe(state, "M15")
        return b

    def signal(
        self,
        vote: int,
        confidence: float,
        reasoning: str,
        metadata: dict[str, Any] | None = None,
        *,
        veto: str | None = None,
        timeframe: str | None = None,
    ) -> AgentSignal:
        return AgentSignal(
            agent_id=self.id,
            division=self.division,
            vote=vote,
            confidence=confidence,
            weight=self.default_weight,
            timeframe=self.timeframe if timeframe is None else timeframe,
            veto=veto,
            reasoning=reasoning,
            metadata=metadata or {},
        )

    def neutral(
        self,
        reason: str = "insufficient data",
        *,
        timeframe: str | None = None,
        **metadata: Any,
    ) -> AgentSignal:
        return self.signal(
            vote=VOTE_NEUTRAL,
            confidence=0.0,
            reasoning=reason,
            metadata=metadata,
            timeframe=timeframe,
        )


__all__ = ["TECHNICAL_WEIGHT", "DIVISION", "TechnicalAgent"]
