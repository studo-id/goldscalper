"""Base class for SPK-core meta-agents.

These agents **observe** the decision context (division scores, HTF/LTF
conflict, calibration, per-agent track record) and attach diagnostics to their
signal metadata. They are deliberately **vote-neutral** and carry zero
confidence: the authoritative aggregation/veto/decision logic lives in the
:mod:`spk` engine and the orchestrator, so these agents must never double-count
votes.
"""

from __future__ import annotations

from typing import Any

from agents.base import AgentSignal, BaseAgent
from agents.state import VOTE_NEUTRAL

# BLUEPRINT §5.2 — the decision brain.
SPK_CORE_WEIGHT = 1.5
DIVISION = "spk_core"


class SPKCoreAgent(BaseAgent):
    """Vote-neutral meta-agent."""

    division = DIVISION
    timeframe: str | None = None

    def __init__(self) -> None:
        super().__init__()
        self.division = DIVISION
        self.default_weight = SPK_CORE_WEIGHT

    def report(self, reasoning: str, metadata: dict[str, Any] | None = None) -> AgentSignal:
        """Emit a neutral, informational signal."""
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


__all__ = ["SPK_CORE_WEIGHT", "DIVISION", "SPKCoreAgent"]
