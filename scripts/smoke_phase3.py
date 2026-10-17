"""Phase 3 smoke — timeframe division through the real orchestrator.

Registers the 8 timeframe agents in a live :class:`AgentRegistry`, runs decision
cycles against Redis + TimescaleDB with synthetic OHLCV, and prints the SPK
result (including HTF vetoes).

Run inside the compose network:
    docker compose run --rm bot python scripts/smoke_phase3.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.divisions.timeframe import build_timeframe_agents  # noqa: E402
from agents.message_bus import MessageBus  # noqa: E402
from agents.orchestrator import Orchestrator  # noqa: E402
from agents.registry import AgentRegistry  # noqa: E402
from agents.state import SharedState  # noqa: E402
from core.market_data import Candle, tf_seconds  # noqa: E402
from data.repositories import AgentDecisionRepository  # noqa: E402

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
SYMBOL = "XAUUSD"


def _frame(tf: str, rows: list[tuple[float, float, float, float]]) -> list[Candle]:
    step = tf_seconds(tf)
    return [
        Candle(SYMBOL, tf, BASE + timedelta(seconds=step * i), o, h, low, c)
        for i, (o, h, low, c) in enumerate(rows)
    ]


# Bullish LTF, ranging/flat HTF (keeps price off extremes so HTF vetoes stay clear).
_BULL_LTF = [(2350 + i, 2351 + i, 2349 + i, 2350.5 + i) for i in range(10)]
_FLAT_HTF = [(2350, 2351, 2349, 2350) for _ in range(10)]
_BEAR_H1 = [(2360 - i, 2361 - i, 2359 - i, 2359.5 - i) for i in range(10)]


def _builder(bullish: bool):
    def build() -> SharedState:
        frames = {
            "M1": _frame("M1", _BULL_LTF),
            "M5": _frame("M5", _BULL_LTF),
            "M15": _frame("M15", _BULL_LTF),
            "M30": _frame("M30", _BULL_LTF),
            "H1": _frame("H1", _BEAR_H1 if not bullish else _FLAT_HTF),
            "H4": _frame("H4", _FLAT_HTF),
            "D1": _frame("D1", _FLAT_HTF),
        }
        return SharedState(
            symbol=SYMBOL,
            frames=frames,
            extra={"eurusd": 1.10, "usdjpy": 150.0, "gbpusd": 1.27},
        )

    return build


async def _run(label: str, bullish: bool) -> None:
    bus = MessageBus()
    repo = AgentDecisionRepository()
    registry = AgentRegistry()
    registry.register_all(build_timeframe_agents())

    orch = Orchestrator(
        registry,
        bus=bus,
        state_builder=_builder(bullish),
        decision_repo=repo,
        broadcast=False,
    )
    decision = await orch.run_cycle()
    votes = " ".join(f"{v.agent_id}={v.vote:+d}" for v in decision.votes)
    print(f"[{label}] action={decision.action} strength={decision.strength} "
          f"score={decision.score} conf={decision.confidence} hard_veto={decision.hard_veto}")
    print(f"[{label}] votes: {votes}")
    if decision.hard_veto:
        print(f"[{label}] veto_reason: {decision.veto_reason}")
    await bus.close()


async def main() -> None:
    await _run("bullish-LTF", bullish=True)
    await _run("bearish-H1", bullish=False)
    print("SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
