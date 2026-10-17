"""Agent, division, and SPK-introspection endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from agents.state import VOTE_BUY, VOTE_SELL
from api.auth import require_token
from api.deps import RuntimeDep

router = APIRouter(
    prefix="/api", tags=["agents"], dependencies=[Depends(require_token)]
)


def _division_rollup(runtime: Any) -> dict[str, Any]:
    """Aggregate per-division vote counts and SPK score contributions."""
    agents = runtime.registry.all()
    decision = runtime.orchestrator.last_decision
    votes = {v.agent_id: v for v in (decision.votes if decision else [])}
    rollup: dict[str, dict[str, Any]] = {}

    def _bucket(name: str) -> dict[str, Any]:
        return rollup.setdefault(
            name, {"agents": 0, "buy": 0, "sell": 0, "neutral": 0, "score": 0.0}
        )

    for agent in agents:
        bucket = _bucket(agent.division)
        bucket["agents"] += 1
        vote = votes.get(agent.id)
        if vote is None:
            bucket["neutral"] += 1
        elif vote.vote == VOTE_BUY:
            bucket["buy"] += 1
        elif vote.vote == VOTE_SELL:
            bucket["sell"] += 1
        else:
            bucket["neutral"] += 1

    if decision:
        for name, score in (decision.division_scores or {}).items():
            _bucket(name)["score"] = round(float(score), 4)
    return rollup


@router.get("/agents")
async def agents(runtime: RuntimeDep) -> dict[str, Any]:
    return {"agents": runtime.agent_health()}


@router.get("/agents/divisions")
async def divisions(runtime: RuntimeDep) -> dict[str, Any]:
    return {"divisions": _division_rollup(runtime)}


@router.get("/spk/latest")
async def spk_latest(runtime: RuntimeDep) -> dict[str, Any]:
    decision = runtime.orchestrator.last_decision
    return {
        "decision": decision.as_dict() if decision is not None else None,
        "cycles": runtime.orchestrator.cycle_count,
    }


@router.get("/patterns")
async def patterns(runtime: RuntimeDep) -> dict[str, Any]:
    return {"best": runtime.patterns.top(10), "worst": runtime.patterns.worst(10)}


__all__ = ["router"]
