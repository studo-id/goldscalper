"""Base class for infra-division agents.

Infra agents are **health-only**: they monitor data freshness, connectivity,
and resource pressure, attach diagnostics, and never vote (BLUEPRINT §5.2 —
"Health only (no vote)").
"""

from __future__ import annotations

from typing import Any

from agents.base import AgentSignal, BaseAgent
from agents.state import VOTE_NEUTRAL

INFRA_WEIGHT = 0.5
DIVISION = "infra"


class InfraAgent(BaseAgent):
    """Vote-neutral infra/health agent."""

    division = DIVISION
    timeframe: str | None = None

    def __init__(self) -> None:
        super().__init__()
        self.division = DIVISION
        self.default_weight = INFRA_WEIGHT

    def report(self, reasoning: str, metadata: dict[str, Any] | None = None) -> AgentSignal:
        return AgentSignal(
            agent_id=self.id,
            division=self.division,
            vote=VOTE_NEUTRAL,
            confidence=0.0,
            weight=self.default_weight,
            timeframe=None,
            reasoning=reasoning,
            metadata=metadata or {},
        )


__all__ = ["INFRA_WEIGHT", "DIVISION", "InfraAgent"]
