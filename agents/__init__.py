"""GoldScalper agent framework."""

from agents.base import AgentSignal, BaseAgent, DummyAgent
from agents.message_bus import Bus, MemoryBus, MessageBus
from agents.orchestrator import Orchestrator
from agents.registry import AgentRegistry
from agents.state import SharedState

__all__ = [
    "AgentSignal",
    "BaseAgent",
    "DummyAgent",
    "Bus",
    "MemoryBus",
    "MessageBus",
    "Orchestrator",
    "AgentRegistry",
    "SharedState",
]
