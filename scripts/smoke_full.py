"""Full-roster smoke — all divisions + pre-trade gate through the orchestrator.

Registers every division agent, runs the decision loop with
:func:`execution.risk_gate.apply` as the gate, and prints the resulting
decision plus division participation.

Run inside the compose network:
    docker compose run --rm bot python scripts/smoke_full.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.divisions import build_all_agents  # noqa: E402
from agents.message_bus import MessageBus  # noqa: E402
from agents.orchestrator import Orchestrator  # noqa: E402
from agents.registry import AgentRegistry  # noqa: E402
from agents.state import SharedState  # noqa: E402
from core.market_data import Candle, tf_seconds  # noqa: E402
from data.repositories import AgentDecisionRepository  # noqa: E402
from execution.risk_gate import apply as risk_gate_apply  # noqa: E402

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
SYMBOL = "XAUUSD"

_BULL = [(2350 + i, 2351 + i, 2349 + i, 2350.5 + i) for i in range(30)]
_FLAT = [(2350, 2351, 2349, 2350) for _ in range(30)]
_BEAR = [(2380 - i, 2381 - i, 2379 - i, 2379.5 - i) for i in range(30)]


def _frame(tf: str, rows: list[tuple[float, float, float, float]]) -> list[Candle]:
    step = tf_seconds(tf)
    return [
        Candle(SYMBOL, tf, BASE + timedelta(seconds=step * i), o, h, low, c, volume=2.0)
        for i, (o, h, low, c) in enumerate(rows)
    ]


def _builder(bullish: bool, **ctx: object):
    def build() -> SharedState:
        trend = _BULL if bullish else _BEAR
        frames = {
            "M1": _frame("M1", trend),
            "M5": _frame("M5", trend),
            "M15": _frame("M15", trend),
            "M30": _frame("M30", trend),
            "H1": _frame("H1", trend),
            "H4": _frame("H4", _FLAT),
            "D1": _frame("D1", _FLAT),
        }
        return SharedState(
            symbol=SYMBOL, frames=frames, bid=2350.0, ask=2350.3, **ctx
        )  # type: ignore[arg-type]

    return build


async def _run(label: str, *, bullish: bool, **ctx: object) -> None:
    bus = MessageBus()
    registry = AgentRegistry()
    registry.register_all(build_all_agents())

    orch = Orchestrator(
        registry,
        bus=bus,
        state_builder=_builder(bullish, **ctx),
        decision_repo=AgentDecisionRepository(),
        risk_gate=risk_gate_apply,
        broadcast=False,
    )
    decision = await orch.run_cycle()
    divisions = sorted(decision.division_scores)
    print(
        f"[{label}] agents={registry.size} action={decision.action} "
        f"score={decision.score} conf={decision.confidence} veto={decision.hard_veto} "
        f"size={decision.size} sl={decision.sl} tp={decision.tp}"
    )
    print(f"[{label}] divisions={divisions}")
    if decision.veto_reason:
        print(f"[{label}] reason: {decision.veto_reason}")
    await bus.close()


async def main() -> None:
    await _run("bullish", bullish=True, equity=10000.0, spread_points=15)
    await _run("bearish", bullish=False, equity=10000.0, spread_points=15)
    await _run(
        "blackout",
        bullish=True,
        equity=10000.0,
        spread_points=15,
        extra={"news_blackout": True},
    )
    print("SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
