"""Agent divisions.

Each division groups a set of specialised agents that vote within the SPK.
:func:`build_all_agents` assembles the full roster for the runtime.
"""

from __future__ import annotations

from agents.base import BaseAgent
from agents.divisions.fundamental import build_fundamental_agents
from agents.divisions.infra import build_infra_agents
from agents.divisions.risk import build_risk_agents
from agents.divisions.spk_core import build_spk_core_agents
from agents.divisions.structure import build_structure_agents
from agents.divisions.technical import build_technical_agents
from agents.divisions.timeframe import build_timeframe_agents

__all__ = [
    "build_all_agents",
    "build_timeframe_agents",
    "build_risk_agents",
    "build_structure_agents",
    "build_technical_agents",
    "build_fundamental_agents",
    "build_spk_core_agents",
    "build_infra_agents",
]


def build_all_agents(*, include_dxy: bool = True) -> list[BaseAgent]:
    """Instantiate every division's agents (full ~36-agent roster)."""
    return [
        *build_timeframe_agents(include_dxy=include_dxy),
        *build_risk_agents(),
        *build_structure_agents(),
        *build_technical_agents(),
        *build_fundamental_agents(),
        *build_spk_core_agents(),
        *build_infra_agents(),
    ]
