"""Orchestrator: the decision loop.

Each cycle it snapshots state, fans out evaluation to every active agent in
parallel, aggregates weighted votes, applies vetoes, produces an
:class:`~spk.decision.SPKDecision`, and broadcasts/persists the result.

The execution step is intentionally not wired here yet (Phase 8); the
orchestrator emits decisions and events that the execution layer will consume.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from agents.base import AgentSignal
from agents.message_bus import Bus, MemoryBus
from agents.registry import AgentRegistry
from agents.state import SharedState, utcnow
from config.logging import get_logger
from config.settings import Settings
from config.settings import settings as default_settings
from spk.decision import ACTION_BUY, ACTION_HOLD, ACTION_SELL, SPKDecision
from spk.veto import VetoParams
from spk.veto import evaluate as evaluate_vetoes
from spk.voting import (
    SPKThresholds,
    action_for_score,
    aggregate,
    confidence_from,
)

log = get_logger("agents.orchestrator")

StateBuilder = Callable[[], Awaitable[SharedState] | SharedState]


class Orchestrator:
    """Runs the multi-agent SPK decision cycle."""

    def __init__(
        self,
        registry: AgentRegistry,
        *,
        settings: Settings | None = None,
        bus: Bus | None = None,
        state_builder: StateBuilder | None = None,
        decision_repo: Any | None = None,
        thresholds: SPKThresholds | None = None,
        veto_params: VetoParams | None = None,
        risk_gate: Callable[..., Any] | None = None,
        broadcast: bool = True,
        lesson_repo: Any | None = None,
        analyzer: Callable[..., Any] | None = None,
        bandit: Any | None = None,
        pattern_library: Any | None = None,
    ) -> None:
        self.registry = registry
        self.settings = settings or default_settings
        self.bus = bus or MemoryBus()
        self.state_builder = state_builder
        self.decision_repo = decision_repo
        self.thresholds = thresholds or SPKThresholds()
        self.veto_params = veto_params or VetoParams(
            max_spread_points=self.settings.max_spread_points
        )
        self.risk_gate = risk_gate
        self.broadcast = broadcast
        self.lesson_repo = lesson_repo
        self.analyzer = analyzer
        self.bandit = bandit
        self.pattern_library = pattern_library

        self._running = False
        self._task: asyncio.Task | None = None
        self.cycle_count = 0
        self.last_decision: SPKDecision | None = None
        self.last_state: SharedState | None = None

    # --- state -----------------------------------------------------------------
    async def _build_state(self) -> SharedState:
        if self.state_builder is None:
            return SharedState(symbol=self.settings.mt5_symbol)
        result = self.state_builder()
        if isinstance(result, Awaitable):
            return await result
        return result

    # --- one cycle -------------------------------------------------------------
    async def run_cycle(self) -> SPKDecision:
        state = await self._build_state()
        self.last_state = state

        agents = self.registry.active()
        signals: list[AgentSignal] = await asyncio.gather(
            *[
                agent.run_cycle(state, bus=self.bus, weight=self.registry.weight(agent.id))
                for agent in agents
            ]
        )

        result = aggregate(signals)
        reload_side = state.extra.get("predator_reload_side") if state else None
        portfolio_state = {
            "daily_pnl_pct": getattr(state, "daily_pnl_pct", 0.0),
            "remaining_target_usd": state.extra.get("remaining_target_usd") if state else None,
            "daily_profit_locked": getattr(state, "daily_profit_locked", False),
        } if state else None
        action, strength = action_for_score(
            result.score, self.thresholds, result=result, reload_side=reload_side, portfolio_state=portfolio_state
        )

        decision = SPKDecision(
            action=action,
            strength=strength,
            score=result.score,
            buy_score=result.buy_score,
            sell_score=result.sell_score,
            participation=result.participation,
            agreement=result.agreement,
            division_scores=result.division_scores,
            votes=signals,
            entry=state.last_price(),
        )

        if action != ACTION_HOLD:
            veto = evaluate_vetoes(signals, state, action, self.veto_params)
            decision.hard_veto = veto.hard
            decision.veto_reason = veto.reason
            decision.soft_notes = veto.notes

            confidence = confidence_from(result, self.thresholds) + veto.confidence_delta
            if state and getattr(state, "daily_pnl_pct", 0.0) < 0:
                pnl_drag = max(-0.15, round(state.daily_pnl_pct / 50.0, 4))
                confidence += pnl_drag
            decision.confidence = round(max(0.0, min(1.0, confidence)), 4)

            # Note: If trade is blocked by hard veto (such as S/R barrier), we respect the veto
            # and maintain HOLD discipline. We strictly DO NOT auto-flip the trade direction against
            # multi-agent SPK consensus to prevent catching falling knives or rocket spikes.

            if self.risk_gate is not None and not decision.hard_veto:
                try:
                    self.risk_gate(decision, state, self.settings)
                except Exception as exc:  # noqa: BLE001 - gate failure must not kill loop
                    log.warning("risk gate failed: %s", exc)
        else:
            decision.confidence = 0.0

        self.cycle_count += 1
        self.last_decision = decision

        await self._publish(decision)
        await self._persist(decision)
        await self._broadcast(decision)

        if self.settings.debug:
            log.info(
                "cycle#%d action=%s score=%.3f conf=%.3f veto=%s",
                self.cycle_count,
                decision.action,
                decision.score,
                decision.confidence,
                decision.hard_veto,
            )
        return decision

    # --- learning hook ---------------------------------------------------------
    async def on_trade_closed(
        self,
        trade: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Any | None:
        """Run the post-trade learning loop for a closed trade.

        Builds a lesson card, persists it, nudges the bandit per participating
        agent, and rolls the card into the pattern library. All steps are
        optional and guarded so a failure never breaks the caller.
        """
        ctx = dict(context or {})
        analyzer = self.analyzer
        card: Any | None = None
        try:
            if analyzer is not None:
                card = analyzer(trade, ctx)
            else:
                from agents.learning.post_trade_analyzer import analyze

                card = analyze(trade, ctx)
        except Exception as exc:  # noqa: BLE001
            log.warning("post-trade analysis failed: %s", exc)
            return None

        if card is None:
            return None

        if self.lesson_repo is not None:
            try:
                await self.lesson_repo.save(card.to_repo_fields())
            except Exception as exc:  # noqa: BLE001
                log.warning("lesson persist failed: %s", exc)

        reward = 1.0 if card.outcome == "win" else (-1.0 if card.outcome == "loss" else 0.0)
        agent_ids = ctx.get("agent_ids") or [a.id for a in self.registry.active()]
        if self.bandit is not None and reward != 0.0:
            try:
                self.bandit.update_many(list(agent_ids), reward)
            except Exception as exc:  # noqa: BLE001
                log.warning("bandit update failed: %s", exc)

        if self.pattern_library is not None:
            try:
                self.pattern_library.add(card)
            except Exception as exc:  # noqa: BLE001
                log.warning("pattern rollup failed: %s", exc)

        return card

    # --- side effects ----------------------------------------------------------
    async def _publish(self, decision: SPKDecision) -> None:
        try:
            await self.bus.publish("gs:spk", decision.as_dict())
        except Exception as exc:  # noqa: BLE001
            log.warning("bus publish failed: %s", exc)

    async def _persist(self, decision: SPKDecision) -> None:
        if self.decision_repo is None:
            return
        try:
            await self.decision_repo.save_decision(decision)
        except Exception as exc:  # noqa: BLE001
            log.warning("persist failed: %s", exc)

    async def _broadcast(self, decision: SPKDecision) -> None:
        if not self.broadcast:
            return
        try:
            from api.ws_manager import manager

            await manager.broadcast({"type": "spk_decision", "data": decision.as_dict()})
        except Exception as exc:  # noqa: BLE001 - API layer may be absent (tests/CLI)
            log.debug("broadcast skipped: %s", exc)

    # --- loop ------------------------------------------------------------------
    async def run_forever(self) -> None:
        interval = max(0.05, self.settings.cycle_interval_ms / 1000.0)
        self._running = True
        log.info(
            "orchestrator loop started (interval=%.3fs, agents=%d)",
            interval,
            self.registry.size,
        )
        while self._running:
            started = utcnow()
            try:
                await self.run_cycle()
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                log.error("cycle error: %s", exc)
            elapsed = (utcnow() - started).total_seconds()
            await asyncio.sleep(max(0.0, interval - elapsed))

    def start(self) -> asyncio.Task:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever(), name="spk-orchestrator")
        return self._task

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception) as exc:  # noqa: BLE001
                log.debug("orchestrator task ended: %s", exc)
            self._task = None
        log.info("orchestrator stopped after %d cycles", self.cycle_count)

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "cycles": self.cycle_count,
            "agents": self.registry.size,
            "last_decision": self.last_decision.as_dict() if self.last_decision else None,
            "ts": datetime.now().isoformat(),
        }
