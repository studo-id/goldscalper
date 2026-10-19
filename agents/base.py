"""Base agent contract.

Every analysis unit in GoldScalper is an :class:`BaseAgent`: it evaluates the
shared state and emits a single :class:`AgentSignal` per cycle, carrying a vote,
a confidence, an optional veto flag, and human-readable reasoning.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from agents.state import (
    VETO_ALL,
    VETO_BUY,
    VETO_SELL,
    VOTE_NEUTRAL,
    SharedState,
    utcnow,
)

if TYPE_CHECKING:  # avoid runtime import cycle
    from agents.message_bus import Bus

_logger = logging.getLogger(__name__)

__all__ = ["AgentSignal", "BaseAgent", "VOTE_NEUTRAL", "VETO_BUY", "VETO_SELL", "VETO_ALL"]


@dataclass
class AgentSignal:
    """The output of one agent for one decision cycle."""

    agent_id: str
    division: str
    vote: int = VOTE_NEUTRAL
    confidence: float = 0.0
    weight: float = 1.0
    timeframe: str | None = None
    veto: str | None = None
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    ts: Any = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        self.vote = max(-1, min(1, self.vote))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        self.weight = max(0.0, float(self.weight))

    @property
    def score(self) -> float:
        """Weighted contribution to the consensus score."""
        return self.vote * self.confidence * self.weight

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if hasattr(self.ts, "isoformat"):
            d["ts"] = self.ts.isoformat()
        elif self.ts is not None:
            d["ts"] = str(self.ts)
        return d


class BaseAgent(ABC):
    """Abstract base for all agents.

    Subclasses implement :meth:`evaluate`. The framework calls
    :meth:`run_cycle`, which handles timing, error isolation, weight attachment,
    signal normalisation, and message-bus publication.
    """

    #: stable identifier, e.g. "TF-M1-Sniper"
    id: str = "agent"
    #: division key, e.g. "timeframe"
    division: str = "misc"
    #: optional timeframe label, e.g. "M1"
    timeframe: str | None = None
    #: default weight used before the learning loop tunes it
    default_weight: float = 1.0

    def __init__(self, agent_id: str | None = None) -> None:
        if agent_id:
            self.id = agent_id
        # runtime observability
        self.last_signal: AgentSignal | None = None
        self.last_run_ts = None
        self.last_latency_ms: float = 0.0
        self.error_count: int = 0
        self.last_error: str | None = None

    @abstractmethod
    async def evaluate(self, state: SharedState) -> AgentSignal:
        """Return this agent's signal for the given state. Must be implemented."""

    async def run_cycle(
        self,
        state: SharedState,
        bus: Bus | None = None,
        stream: str = "gs:signals",
        weight: float | None = None,
    ) -> AgentSignal:
        """Evaluate, time, and optionally publish one signal.

        Errors are contained: on exception the agent yields a neutral signal so
        one failing agent never blocks the cycle.
        """
        started = time.perf_counter()
        try:
            signal = await self.evaluate(state)
            if not isinstance(signal, AgentSignal):
                raise TypeError(
                    f"{self.id}.evaluate() must return AgentSignal, got {type(signal)!r}"
                )
        except Exception as exc:  # noqa: BLE001 - contain agent failures
            self.error_count += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            signal = AgentSignal(
                agent_id=self.id,
                division=self.division,
                vote=VOTE_NEUTRAL,
                confidence=0.0,
                weight=weight if weight is not None else self.default_weight,
                timeframe=self.timeframe,
                reasoning=f"error: {self.last_error}",
            )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        signal.latency_ms = round(elapsed_ms, 3)
        if not signal.agent_id:
            signal.agent_id = self.id
        if not signal.division:
            signal.division = self.division
        if signal.timeframe is None:
            signal.timeframe = self.timeframe
        if weight is not None:
            signal.weight = weight

        # record observability
        self.last_signal = signal
        self.last_latency_ms = signal.latency_ms
        self.last_run_ts = signal.ts

        if bus is not None:
            try:
                await bus.publish(stream, signal.as_dict())
            except Exception as exc:  # noqa: BLE001 - bus failures must not kill agent
                _logger.debug("bus publish failed for %s: %s", self.id, exc)
        return signal

    def health(self) -> dict[str, Any]:
        """Small health snapshot for the API/UI."""
        return {
            "id": self.id,
            "division": self.division,
            "timeframe": self.timeframe,
            "default_weight": self.default_weight,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "last_latency_ms": self.last_latency_ms,
            "last_vote": self.last_signal.vote if self.last_signal else None,
            "last_confidence": self.last_signal.confidence if self.last_signal else None,
        }


class DummyAgent(BaseAgent):
    """Configurable agent for tests and framework smoke checks."""

    def __init__(
        self,
        agent_id: str,
        division: str = "test",
        vote: int = VOTE_NEUTRAL,
        confidence: float = 0.5,
        weight: float = 1.0,
        veto: str | None = None,
        timeframe: str | None = None,
        raise_error: bool = False,
    ) -> None:
        super().__init__(agent_id)
        self.division = division
        self.default_weight = weight
        self.timeframe = timeframe
        self._vote = vote
        self._confidence = confidence
        self._veto = veto
        self._raise = raise_error

    async def evaluate(self, state: SharedState) -> AgentSignal:
        if self._raise:
            raise RuntimeError("dummy agent failure")
        return AgentSignal(
            agent_id=self.id,
            division=self.division,
            vote=self._vote,
            confidence=self._confidence,
            weight=self.default_weight,
            veto=self._veto,
            timeframe=self.timeframe,
            reasoning="dummy",
        )
