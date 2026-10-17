"""Phase 4 smoke — risk division + pre-trade gate through the orchestrator.

Registers timeframe + risk agents, runs the decision loop with
:func:`execution.risk_gate.apply` as the gate, and prints the resolved
size/SL/TP (or the block reason).

Run inside the compose network:
    docker compose run --rm bot python scripts/smoke_phase4.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.divisions.risk import build_risk_agents  # noqa: E402
from agents.divisions.timeframe import build_timeframe_agents  # noqa: E402
from agents.message_bus import MessageBus  # noqa: E402
from agents.orchestrator import Orchestrator  # noqa: E402
from agents.registry import AgentRegistry  # noqa: E402
from agents.state import SharedState  # noqa: E402
from core.market_data import Candle, tf_seconds  # noqa: E402
from data.repositories import AgentDecisionRepository  # noqa: E402
from execution.risk_gate import apply as risk_gate_apply  # noqa: E402

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
SYMBOL = "XAUUSD"

_BULL_LTF = [(2350 + i, 2351 + i, 2349 + i, 2350.5 + i) for i in range(10)]
_FLAT_HTF = [(2350, 2351, 2349, 2350) for _ in range(20)]
_BEAR_H1 = [(2360 - i, 2361 - i, 2359 - i, 2359.5 - i) for i in range(10)]


def _frame(tf: str, rows: list[tuple[float, float, float, float]]) -> list[Candle]:
    step = tf_seconds(tf)
    return [
        Candle(SYMBOL, tf, BASE + timedelta(seconds=step * i), o, h, low, c)
        for i, (o, h, low, c) in enumerate(rows)
    ]


def _builder(*, bullish: bool, **ctx: object):
    def build() -> SharedState:
        frames = {
            "M1": _frame("M1", _BULL_LTF),
            "M5": _frame("M5", _BULL_LTF),
            "M15": _frame("M15", _BULL_LTF),
            "M30": _frame("M30", _BULL_LTF),
            "H1": _frame("H1", _FLAT_HTF if bullish else _BEAR_H1),
            "H4": _frame("H4", _FLAT_HTF),
            "D1": _frame("D1", _FLAT_HTF),
        }
        return SharedState(
            symbol=SYMBOL, frames=frames, bid=2350.0, ask=2350.3, **ctx
        )  # type: ignore[arg-type]

    return build


async def _run(label: str, *, bullish: bool, **ctx: object) -> None:
    bus = MessageBus()
    registry = AgentRegistry()
    registry.register_all(build_timeframe_agents())
    registry.register_all(build_risk_agents())

    orch = Orchestrator(
        registry,
        bus=bus,
        state_builder=_builder(bullish=bullish, **ctx),
        decision_repo=AgentDecisionRepository(),
        risk_gate=risk_gate_apply,
        broadcast=False,
    )
    decision = await orch.run_cycle()
    print(
        f"[{label}] action={decision.action} score={decision.score} "
        f"conf={decision.confidence} veto={decision.hard_veto} "
        f"size={decision.size} sl={decision.sl} tp={decision.tp}"
    )
    if decision.veto_reason:
        print(f"[{label}] reason: {decision.veto_reason}")
    await bus.close()


async def main() -> None:
    await _run("tradable", bullish=True, equity=10000.0, spread_points=15)
    await _run("htf-veto", bullish=False, equity=10000.0, spread_points=15)
    await _run("drawdown-halt", bullish=True, equity=10000.0, spread_points=15, daily_pnl_pct=-4.0)
    print("SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
