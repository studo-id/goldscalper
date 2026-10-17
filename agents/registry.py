"""Agent registry: discovery, weighting, and lifecycle.

Holds the active agent pool, resolves per-agent weights (defaults, later tuned
by the learning loop), and provides division/pool accessors used by the
orchestrator.
"""

from __future__ import annotations

from collections import defaultdict

from agents.base import BaseAgent
from config.logging import get_logger

log = get_logger("agents.registry")


class AgentRegistry:
    """In-memory registry of agents with adaptive weights."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._weights: dict[str, float] = {}

    # --- Registration ----------------------------------------------------------
    def register(self, agent: BaseAgent) -> None:
        if agent.id in self._agents:
            raise ValueError(f"agent id already registered: {agent.id}")
        self._agents[agent.id] = agent
        self._weights.setdefault(agent.id, agent.default_weight)
        log.info("registered agent %s (division=%s)", agent.id, agent.division)

    def register_all(self, agents: list[BaseAgent]) -> None:
        for agent in agents:
            self.register(agent)

    def unregister(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)
        self._weights.pop(agent_id, None)

    def clear(self) -> None:
        self._agents.clear()
        self._weights.clear()

    # --- Access ----------------------------------------------------------------
    @property
    def size(self) -> int:
        return len(self._agents)

    def get(self, agent_id: str) -> BaseAgent | None:
        return self._agents.get(agent_id)

    def all(self) -> list[BaseAgent]:
        return list(self._agents.values())

    def active(self) -> list[BaseAgent]:
        """Agents eligible to vote this cycle (all registered, for now)."""
        return list(self._agents.values())

    def by_division(self, division: str) -> list[BaseAgent]:
        return [a for a in self._agents.values() if a.division == division]

    def divisions(self) -> dict[str, list[BaseAgent]]:
        grouped: dict[str, list[BaseAgent]] = defaultdict(list)
        for agent in self._agents.values():
            grouped[agent.division].append(agent)
        return dict(grouped)

    # --- Weights ---------------------------------------------------------------
    def weight(self, agent_id: str) -> float:
        return self._weights.get(agent_id, 1.0)

    def set_weight(self, agent_id: str, weight: float) -> None:
        self._weights[agent_id] = max(0.0, float(weight))

    def weights(self) -> dict[str, float]:
        return dict(self._weights)

    def load_weights(self, weights: dict[str, float]) -> None:
        """Overlay persisted weights (learning loop / DB) onto defaults."""
        for agent_id, weight in weights.items():
            if agent_id in self._agents:
                self._weights[agent_id] = max(0.0, float(weight))

    # --- Introspection ---------------------------------------------------------
    def health(self) -> list[dict]:
        rows = []
        for agent in self._agents.values():
            row = agent.health()
            row["weight"] = self.weight(agent.id)
            rows.append(row)
        return rows
