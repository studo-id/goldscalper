"""SPK decision model.

The final, executable output of a decision cycle. Aggregation and veto logic
live in :mod:`spk.voting` and :mod:`spk.veto`; this module only models the
result and its serialization.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from agents.state import utcnow

# Actions
ACTION_BUY = "BUY"
ACTION_SELL = "SELL"
ACTION_HOLD = "HOLD"

# Strength
STRENGTH_STRONG = "STRONG"
STRENGTH_NORMAL = "NORMAL"
STRENGTH_NONE = "NONE"


@dataclass
class SPKDecision:
    """Consensus decision produced by the SPK core."""

    action: str = ACTION_HOLD
    strength: str = STRENGTH_NONE
    score: float = 0.0
    confidence: float = 0.0

    # execution intent (filled by risk agents / position sizing later)
    size: float = 0.0
    sl: float | None = None
    tp: float | None = None
    entry: float | None = None

    # veto info
    hard_veto: bool = False
    veto_reason: str | None = None
    soft_notes: list[str] = field(default_factory=list)

    # diagnostics
    buy_score: float = 0.0
    sell_score: float = 0.0
    participation: int = 0
    agreement: float = 0.0
    division_scores: dict[str, float] = field(default_factory=dict)
    votes: list[Any] = field(default_factory=list)  # list[AgentSignal]

    ts: datetime = field(default_factory=utcnow)

    @property
    def tradable(self) -> bool:
        return not self.hard_veto and self.action in (ACTION_BUY, ACTION_SELL)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "strength": self.strength,
            "score": self.score,
            "confidence": self.confidence,
            "size": self.size,
            "sl": self.sl,
            "tp": self.tp,
            "entry": self.entry,
            "hard_veto": self.hard_veto,
            "veto_reason": self.veto_reason,
            "soft_notes": self.soft_notes,
            "buy_score": self.buy_score,
            "sell_score": self.sell_score,
            "participation": self.participation,
            "agreement": self.agreement,
            "division_scores": self.division_scores,
            "tradable": self.tradable,
            "ts": self.ts.isoformat() if hasattr(self.ts, "isoformat") else str(self.ts),
            "votes": [
                v.as_dict() if hasattr(v, "as_dict") else (
                    {
                        "agent_id": getattr(v, "agent_id", str(v)),
                        "division": getattr(v, "division", ""),
                        "vote": getattr(v, "vote", 0),
                        "confidence": getattr(v, "confidence", 0.0),
                        "weight": getattr(v, "weight", 1.0),
                        "timeframe": getattr(v, "timeframe", None),
                        "veto": getattr(v, "veto", None),
                        "reasoning": getattr(v, "reasoning", ""),
                        "latency_ms": getattr(v, "latency_ms", 0.0),
                        "ts": v.ts.isoformat() if hasattr(getattr(v, "ts", None), "isoformat") else str(getattr(v, "ts", "")),
                    } if not isinstance(v, dict) else v
                )
                for v in self.votes
            ],
        }
