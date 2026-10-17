"""Bandit optimizer (Thompson sampling).

Maintains a Beta posterior over each agent's win/loss record and samples from
it to propose adaptive weights. Exploration is bounded so weights never drift
faster than the configured weekly cap; human approval (Phase 9 policy) still
gates large deltas.

Deterministic when seeded — safe for tests and reproducible runs.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from config.logging import get_logger

log = get_logger("learning.bandit")


@dataclass
class BanditOptimizer:
    """Per-agent Thompson-sampling weight proposer."""

    exploration: float = 0.1
    weight_max_delta_pct: float = 20.0
    seed: int = 7
    _alpha: dict[str, float] = field(default_factory=dict)
    _beta: dict[str, float] = field(default_factory=dict)
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)  # noqa: S311 - deterministic simulation

    # --- updates ---------------------------------------------------------------
    def update(self, agent_id: str, reward: float) -> None:
        """Record an outcome: reward > 0 is a win, <= 0 a loss."""
        if reward > 0:
            self._alpha[agent_id] = self._alpha.get(agent_id, 1.0) + 1.0
        else:
            self._beta[agent_id] = self._beta.get(agent_id, 1.0) + 1.0

    def update_many(self, agent_ids: list[str], reward: float) -> None:
        for agent_id in agent_ids:
            self.update(agent_id, reward)

    # --- posteriors ------------------------------------------------------------
    def _params(self, agent_id: str) -> tuple[float, float]:
        return self._alpha.get(agent_id, 1.0), self._beta.get(agent_id, 1.0)

    def winrate(self, agent_id: str) -> float:
        """Posterior mean win rate."""
        a, b = self._params(agent_id)
        return a / (a + b)

    def sample(self, agent_id: str) -> float:
        """Draw from the agent's Beta posterior."""
        a, b = self._params(agent_id)
        return self._rng.betavariate(a, b)

    def suggest_weight(self, agent_id: str, default_weight: float) -> float:
        """Propose a new weight, bounded by the exploration/delta caps."""
        mean = self.winrate(agent_id)
        # de-mean around 0.5 so a 50% agent keeps its default weight
        raw = default_weight * (1.0 + (mean - 0.5) * 2.0 * self.exploration)
        cap = default_weight * (self.weight_max_delta_pct / 100.0)
        lower = max(0.0, default_weight - cap)
        upper = default_weight + cap
        return round(min(upper, max(lower, raw)), 4)

    def suggest(self, defaults: dict[str, float]) -> dict[str, float]:
        return {aid: self.suggest_weight(aid, w) for aid, w in defaults.items()}

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for agent_id in set(self._alpha) | set(self._beta):
            a, b = self._params(agent_id)
            out[agent_id] = {"alpha": a, "beta": b, "winrate": round(self.winrate(agent_id), 4)}
        return out


__all__ = ["BanditOptimizer"]
