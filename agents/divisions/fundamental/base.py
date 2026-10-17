"""Base class for fundamental-division agents.

Fundamental agents are **context voters**: they translate macro / news /
cross-market state (carried on :class:`SharedState.extra`) into a directional
bias. They never block the hot path with network or LLM calls — any sentiment
is pre-computed upstream and injected as state.
"""

from __future__ import annotations

from typing import Any

from agents.base import AgentSignal, BaseAgent
from agents.state import VOTE_NEUTRAL
from config.logging import get_logger

log = get_logger("agents.fundamental")

# BLUEPRINT §5.2 — news/macro filter, low authority.
FUNDAMENTAL_WEIGHT = 0.8
DIVISION = "fundamental"


class FundamentalAgent(BaseAgent):
    """Base fundamental agent (no OHLC dependency by default)."""

    division = DIVISION
    timeframe: str | None = None

    def __init__(self) -> None:
        super().__init__()
        self.division = DIVISION
        self.default_weight = FUNDAMENTAL_WEIGHT

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
        reason: str = "no fundamental input",
        *,
        timeframe: str | None = None,
        **metadata: Any,
    ) -> AgentSignal:
        return self.signal(
            VOTE_NEUTRAL, 0.0, reason, metadata, timeframe=timeframe
        )


__all__ = ["FUNDAMENTAL_WEIGHT", "DIVISION", "FundamentalAgent"]
