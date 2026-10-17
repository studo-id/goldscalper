"""Infra division — health-only agents (3, no vote)."""

from __future__ import annotations

from agents.divisions.infra.agents import (
    INFRA_AGENT_CLASSES,
    Connectivity,
    Heartbeat,
    Resource,
)
from agents.divisions.infra.base import DIVISION, INFRA_WEIGHT, InfraAgent

__all__ = [
    "DIVISION",
    "INFRA_WEIGHT",
    "InfraAgent",
    "Heartbeat",
    "Connectivity",
    "Resource",
    "INFRA_AGENT_CLASSES",
    "build_infra_agents",
]


def build_infra_agents() -> list[InfraAgent]:
    """Instantiate the three infra-division agents."""
    return [cls() for cls in INFRA_AGENT_CLASSES]
