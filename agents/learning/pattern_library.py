"""Pattern library.

Rolls lesson cards up into recurring ``(regime, root_cause)`` patterns with
win rate and average P&L, so the system can surface "what keeps going wrong"
and "what keeps working".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.learning.post_trade_analyzer import (
    OUTCOME_WIN,
    LessonCard,
)


@dataclass
class PatternStat:
    regime: str | None
    root_cause: str
    count: int = 0
    wins: int = 0
    total_pnl: float = 0.0

    @property
    def winrate(self) -> float:
        return (self.wins / self.count) if self.count else 0.0

    @property
    def avg_pnl(self) -> float:
        return (self.total_pnl / self.count) if self.count else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "root_cause": self.root_cause,
            "count": self.count,
            "wins": self.wins,
            "winrate": round(self.winrate, 4),
            "avg_pnl": round(self.avg_pnl, 4),
        }


@dataclass
class PatternLibrary:
    _stats: dict[tuple[str | None, str], PatternStat] = field(default_factory=dict)

    def add(self, card: LessonCard) -> PatternStat:
        key = (card.regime, card.root_cause)
        stat = self._stats.get(key)
        if stat is None:
            stat = PatternStat(regime=card.regime, root_cause=card.root_cause)
            self._stats[key] = stat
        stat.count += 1
        if card.outcome == OUTCOME_WIN:
            stat.wins += 1
        stat.total_pnl += float(card.metadata.get("pnl", 0.0) or 0.0)
        return stat

    def add_many(self, cards: list[LessonCard]) -> None:
        for card in cards:
            self.add(card)

    def entries(self) -> list[PatternStat]:
        return sorted(self._stats.values(), key=lambda s: s.count, reverse=True)

    def top(self, n: int = 5) -> list[dict[str, Any]]:
        return [s.as_dict() for s in self.entries()[:n]]

    def worst(self, n: int = 5) -> list[dict[str, Any]]:
        ordered = sorted(self._stats.values(), key=lambda s: s.winrate)
        return [s.as_dict() for s in ordered[:n]]

    def as_dict(self) -> dict[str, Any]:
        return {"patterns": [s.as_dict() for s in self.entries()]}


__all__ = ["PatternStat", "PatternLibrary"]
