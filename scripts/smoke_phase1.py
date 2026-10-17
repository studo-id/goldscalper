"""Phase 1 smoke test — exercises the full framework against live services.

Builds a small dummy registry, runs one orchestrator cycle using the real Redis
Streams bus and the real ``agent_decisions`` persistence, then verifies side
effects.

Run inside the compose network:
    docker compose run --rm bot python scripts/smoke_phase1.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.base import DummyAgent  # noqa: E402
from agents.message_bus import MessageBus  # noqa: E402
from agents.orchestrator import Orchestrator  # noqa: E402
from agents.registry import AgentRegistry  # noqa: E402
from agents.state import VOTE_BUY, VOTE_NEUTRAL, VOTE_SELL, SharedState  # noqa: E402
from data.repositories import AgentDecisionRepository  # noqa: E402


async def main() -> None:
    registry = AgentRegistry()
    registry.register_all(
        [
            DummyAgent(
                "TF-M1-Sniper", division="timeframe",
                vote=VOTE_BUY, confidence=0.7, weight=1.2,
            ),
            DummyAgent(
                "TF-M5-Inspector", division="timeframe",
                vote=VOTE_BUY, confidence=0.6, weight=1.2,
            ),
            DummyAgent(
                "TF-H1-Regime", division="timeframe",
                vote=VOTE_NEUTRAL, confidence=0.9, weight=1.5,
            ),
            DummyAgent(
                "Risk-PositionSizer", division="risk",
                vote=VOTE_BUY, confidence=0.8, weight=2.0,
            ),
            DummyAgent(
                "Struct-Session", division="structure",
                vote=VOTE_SELL, confidence=0.3, weight=1.3,
            ),
        ]
    )

    def _state() -> SharedState:
        return SharedState(
            symbol="XAUUSD",
            bid=2350.10,
            ask=2350.35,
            spread_points=25,
            session="london",
        )

    bus = MessageBus()
    repo = AgentDecisionRepository()
    orch = Orchestrator(
        registry,
        bus=bus,
        decision_repo=repo,
        state_builder=_state,
        broadcast=False,
    )

    decision = await orch.run_cycle()
    summary = {
        k: decision.as_dict()[k]
        for k in ("action", "strength", "score", "confidence", "hard_veto", "tradable")
    }
    print("DECISION:", summary)

    # Verify Redis stream received the SPK event.
    client = bus._client_or_create()
    spk_len = await client.xlen("gs:spk")
    signals_len = await client.xlen("gs:signals")
    print(f"redis gs:spk len={spk_len}  gs:signals len={signals_len}")

    # Verify persistence.
    from sqlalchemy import text

    from data.db import get_session_factory

    async with get_session_factory()() as session:
        total = (await session.execute(text("SELECT count(*) FROM agent_decisions"))).scalar_one()
    print(f"agent_decisions rows={total}")

    await bus.close()
    print("SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
