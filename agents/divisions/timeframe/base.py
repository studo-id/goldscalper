"""Base class and OHLCV view for the timeframe division.

Each scout agent reads candles from :attr:`SharedState.frames` (keyed by
timeframe) and emits one :class:`~agents.base.AgentSignal` per cycle. Frames are
accepted as :class:`core.market_data.Candle` objects, plain dicts, or any object
exposing ``open``/``high``/``low``/``close`` attributes.
"""

from __future__ import annotations

from typing import Any

from agents.base import AgentSignal, BaseAgent
from agents.state import VOTE_NEUTRAL, SharedState
from config.logging import get_logger
from core.market_data import Bars

log = get_logger("agents.timeframe")

# Default division weights (BLUEPRINT §5.2).
HTF_WEIGHT = 1.5  # H1, H4, D1 — veto power, macro bias
LTF_WEIGHT = 1.2  # M1, M5, M15, M30 — entry precision

DIVISION = "timeframe"


class TimeframeAgent(BaseAgent):
    """Base scout: resolves bars from shared state and shapes signals."""

    division = DIVISION
    timeframe: str | None = ""
    htf = False
    min_bars = 2

    def __init__(self) -> None:
        super().__init__()
        self.division = DIVISION
        self.default_weight = HTF_WEIGHT if self.htf else LTF_WEIGHT

    def bars(self, state: SharedState) -> Bars:
        """Fetch this agent's timeframe frame from the shared state."""
        return Bars.for_timeframe(state, self.timeframe or "")

    def signal(
        self,
        *,
        vote: int,
        confidence: float,
        reasoning: str,
        metadata: dict[str, Any] | None = None,
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


__all__ = [
    "Bars",
    "TimeframeAgent",
    "DIVISION",
    "HTF_WEIGHT",
    "LTF_WEIGHT",
]
