"""SPK-core meta-agents (IMPLEMENTATION_PLAN Phase 7.1–7.5).

    7.1 SPK-Chief      — final GO / NO-GO summary
    7.2 SPK-Aggregator — per-division weighted score summary
    7.3 SPK-Resolver   — HTF vs LTF conflict resolution view
    7.4 SPK-Confidence — calibrated probability estimate
    7.5 SPK-Tracker    — per-agent win-rate leaderboard

All five are vote-neutral; they only attach diagnostics.
"""

from __future__ import annotations

import math

from agents.base import AgentSignal
from agents.divisions.spk_core.base import SPKCoreAgent
from agents.state import SharedState


class Chief(SPKCoreAgent):
    id = "SPK-Chief"

    async def evaluate(self, state: SharedState) -> AgentSignal:
        action = state.extra.get("action")
        score = state.extra.get("score")
        hard_veto = bool(state.extra.get("hard_veto", False))
        tradable = action in {"BUY", "SELL"} and score is not None and not hard_veto
        return self.report(
            f"GO={tradable} action={action} veto={hard_veto}",
            {
                "go": tradable,
                "action": action,
                "score": score,
                "hard_veto": hard_veto,
                "sizing_authority": tradable,
            },
        )


class Aggregator(SPKCoreAgent):
    id = "SPK-Aggregator"

    async def evaluate(self, state: SharedState) -> AgentSignal:
        divisions: dict[str, float] = dict(state.extra.get("division_scores") or {})
        if not divisions:
            return self.report("no division scores yet", {"divisions": 0})
        net = round(sum(divisions.values()), 4)
        top = max(divisions, key=lambda k: abs(divisions[k]))
        return self.report(
            f"net division score {net}, dominant {top}",
            {
                "division_scores": divisions,
                "net": net,
                "dominant_division": top,
                "dominant_value": round(divisions[top], 4),
            },
        )


class Resolver(SPKCoreAgent):
    id = "SPK-Resolver"

    async def evaluate(self, state: SharedState) -> AgentSignal:
        htf = state.extra.get("htf_vote")
        ltf = state.extra.get("ltf_vote")
        if htf is None and ltf is None:
            return self.report("no HTF/LTF votes to resolve")
        conflict = htf is not None and ltf is not None and (htf * ltf) < 0
        resolution = "higher_timeframe_priority" if conflict else "aligned"
        return self.report(
            f"{resolution} (htf={htf}, ltf={ltf})",
            {"htf_vote": htf, "ltf_vote": ltf, "conflict": conflict, "resolution": resolution},
        )


class Confidence(SPKCoreAgent):
    id = "SPK-Confidence"

    async def evaluate(self, state: SharedState) -> AgentSignal:
        score = state.extra.get("score")
        if score is None:
            return self.report("no score to calibrate")
        participation = state.extra.get("participation")
        probability = 1.0 / (1.0 + math.exp(-abs(float(score))))
        return self.report(
            f"probability {probability:.3f}",
            {
                "score": score,
                "probability": round(probability, 4),
                "participation": participation,
            },
        )


class Tracker(SPKCoreAgent):
    id = "SPK-Tracker"

    async def evaluate(self, state: SharedState) -> AgentSignal:
        winrates: dict[str, float] = dict(state.extra.get("agent_winrates") or {})
        if not winrates:
            return self.report("no track record yet", {"agents": 0})
        best = max(winrates, key=winrates.get)
        worst = min(winrates, key=winrates.get)
        return self.report(
            f"best {best} ({winrates[best]:.2f}), worst {worst} ({winrates[worst]:.2f})",
            {
                "agents": len(winrates),
                "best_agent": best,
                "best_winrate": round(winrates[best], 4),
                "worst_agent": worst,
                "worst_winrate": round(winrates[worst], 4),
            },
        )


SPK_CORE_AGENT_CLASSES: tuple[type[SPKCoreAgent], ...] = (
    Chief,
    Aggregator,
    Resolver,
    Confidence,
    Tracker,
)


__all__ = [
    "Chief",
    "Aggregator",
    "Resolver",
    "Confidence",
    "Tracker",
    "SPK_CORE_AGENT_CLASSES",
]
