"""Infra division agents — health only, no vote.

    Infra-Heartbeat      — data freshness / staleness
    Infra-Connectivity   — MT5 / Redis / DB reachability
    Infra-Resource       — cycle latency / error pressure
"""

from __future__ import annotations

from agents.base import AgentSignal
from agents.divisions.infra.base import InfraAgent
from agents.state import SharedState


class Heartbeat(InfraAgent):
    id = "Infra-Heartbeat"
    tick_stale_s = 5.0
    candle_stale_s = 180.0

    async def evaluate(self, state: SharedState) -> AgentSignal:
        tick_age = state.extra.get("last_tick_age_s")
        candle_age = state.extra.get("last_candle_age_s")
        tick_ok = tick_age is None or tick_age <= self.tick_stale_s
        candle_ok = candle_age is None or candle_age <= self.candle_stale_s
        healthy = tick_ok and candle_ok
        return self.report(
            f"healthy={healthy} tick_age={tick_age} candle_age={candle_age}",
            {
                "healthy": healthy,
                "tick_age_s": tick_age,
                "candle_age_s": candle_age,
                "tick_stale": not tick_ok,
                "candle_stale": not candle_ok,
            },
        )


class Connectivity(InfraAgent):
    id = "Infra-Connectivity"

    async def evaluate(self, state: SharedState) -> AgentSignal:
        mt5 = bool(state.extra.get("mt5_connected", True))
        redis = bool(state.extra.get("redis_ok", True))
        db = bool(state.extra.get("db_ok", True))
        healthy = mt5 and redis and db
        return self.report(
            f"healthy={healthy} mt5={mt5} redis={redis} db={db}",
            {"healthy": healthy, "mt5": mt5, "redis": redis, "db": db},
        )


class Resource(InfraAgent):
    id = "Infra-Resource"
    max_cycle_ms = 500.0
    max_errors = 5

    async def evaluate(self, state: SharedState) -> AgentSignal:
        cycle_ms = state.extra.get("cycle_ms")
        errors = int(state.extra.get("error_count", 0))
        latency_ok = cycle_ms is None or cycle_ms <= self.max_cycle_ms
        errors_ok = errors <= self.max_errors
        healthy = latency_ok and errors_ok
        return self.report(
            f"healthy={healthy} cycle_ms={cycle_ms} errors={errors}",
            {
                "healthy": healthy,
                "cycle_ms": cycle_ms,
                "error_count": errors,
                "latency_ok": latency_ok,
                "errors_ok": errors_ok,
            },
        )


INFRA_AGENT_CLASSES: tuple[type[InfraAgent], ...] = (
    Heartbeat,
    Connectivity,
    Resource,
)


__all__ = ["Heartbeat", "Connectivity", "Resource", "INFRA_AGENT_CLASSES"]
