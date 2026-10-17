"""Pre-trade risk gate.

The single place that turns risk-division *proposals* into an executable
decision. It reads the vote-neutral metadata emitted by the risk agents,
re-validates it against :class:`~config.settings.Settings`, and either blocks the
trade (hard veto) or stamps ``size`` / ``sl`` / ``tp`` onto the
:class:`~spk.decision.SPKDecision`.

Deterministic and LLM-free — safe to run in the hot path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.state import SharedState
from config.logging import get_logger
from config.settings import Settings
from config.settings import settings as default_settings
from spk.decision import ACTION_BUY, ACTION_HOLD, SPKDecision

log = get_logger("execution.risk_gate")

__all__ = ["RiskGateResult", "evaluate", "apply"]

_SIZER = "Risk-PositionSizer"
_STOP = "Risk-StopLoss"
_TP = "Risk-TakeProfit"
_GUARD = "Risk-DrawdownGuard"
_COST = "Risk-CostMonitor"
_TIMING = "Risk-EntryTiming"


def _round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(round(value / step) * step, 4)


def _meta(votes: list[Any], agent_id: str) -> dict[str, Any]:
    for vote in votes or []:
        if getattr(vote, "agent_id", None) == agent_id:
            meta = getattr(vote, "metadata", None)
            if isinstance(meta, dict):
                return meta
    return {}


@dataclass
class RiskGateResult:
    """Outcome of the pre-trade check."""

    approved: bool
    reason: str | None = None
    size: float = 0.0
    sl: float | None = None
    tp: float | None = None
    entry: float | None = None
    notes: list[str] = field(default_factory=list)


def evaluate(
    decision: SPKDecision,
    state: SharedState,
    settings: Settings | None = None,
) -> RiskGateResult:
    """Validate the decision against risk limits and resolve size/SL/TP."""
    s = settings or default_settings

    if decision.action == ACTION_HOLD:
        return RiskGateResult(approved=False, reason="hold")
    if decision.hard_veto:
        return RiskGateResult(
            approved=False,
            reason=f"existing hard veto: {decision.veto_reason or 'blocked'}",
        )

    votes = decision.votes or []

    guard = _meta(votes, _GUARD)
    if guard.get("halt"):
        return RiskGateResult(approved=False, reason=f"drawdown guard: {guard.get('reason')}")

    cost = _meta(votes, _COST)
    if cost and cost.get("cost_ok") is False:
        return RiskGateResult(
            approved=False,
            reason=f"cost rejected (spread {cost.get('spread_points')})",
        )

    timing = _meta(votes, _TIMING)
    if timing and timing.get("spread_ok") is False:
        return RiskGateResult(
            approved=False,
            reason=f"wide spread ({timing.get('spread_points')} > {timing.get('max_spread_points', s.max_spread_points)})",
        )
    if timing and timing.get("friction_blocked") is True:
        return RiskGateResult(
            approved=False,
            reason=f"friction guard: net fee ratio {timing.get('friction_ratio')}% > {s.max_friction_ratio_pct}% (DEFENSE mode)",
        )

    sizer = _meta(votes, _SIZER)
    sl_meta = _meta(votes, _STOP)
    tp_meta = _meta(votes, _TP)

    sl_distance = float(sl_meta.get("sl_distance") or sizer.get("sl_distance") or 0.0)
    tp_distance = float(tp_meta.get("tp_distance") or 0.0)
    base_size = float(sizer.get("size") or 0.0)

    confidence = max(0.0, min(1.0, float(decision.confidence)))
    score = abs(float(decision.score or 0.0))
    is_high_conviction = bool(sizer.get("high_conviction")) or confidence >= 0.70 or score >= 5.0
    daily_pnl_pct = float(getattr(state, "daily_pnl_pct", 0.0) or 0.0) if state else 0.0

    if is_high_conviction or sizer.get("sizing_mode") == "TARGET_SEEKING":
        # Trust Sizer's portfolio-aware dynamic calculation directly
        scaled_size = base_size
    else:
        scaled_size = _round_to_step(base_size * max(0.50, confidence), s.lot_step)
    size = min(s.max_lot, max(s.min_lot, scaled_size)) if base_size >= s.min_lot else scaled_size
    if size < s.min_lot:
        return RiskGateResult(
            approved=False,
            reason=f"resolved size {size} < min lot {s.min_lot}",
            size=size,
        )

    entry = decision.entry if decision.entry is not None else (state.last_price() if state else None)
    if entry is None and state:
        entry = state.ask if decision.action == ACTION_BUY else state.bid
    if entry is None and state and state.bid:
        entry = state.bid

    # Guarantee minimum stop loss and take profit distances
    if sl_distance <= 0:
        spread_usd = (float(state.spread_points or 0.0) * 0.10) if state else 0.80
        sl_distance = max(2.50, round(spread_usd * 2.5, 2))
    if tp_distance <= 0:
        tp_distance = round(sl_distance * s.default_rr, 2)

    # High-Conviction Runner TP Expansion in DEFENSE mode
    if is_high_conviction and daily_pnl_pct < 0:
        tp_distance = max(tp_distance, 7.50, round(sl_distance * 1.80, 2))

    sl: float | None = None
    tp: float | None = None

    if decision.sl is not None:
        sl = decision.sl
    elif entry is not None and sl_distance > 0:
        if decision.action == ACTION_BUY:
            sl = round(entry - sl_distance, 2)
        else:
            sl = round(entry + sl_distance, 2)

    if decision.tp is not None:
        tp = decision.tp
    elif entry is not None and tp_distance > 0:
        if decision.action == ACTION_BUY:
            tp = round(entry + tp_distance, 2)
        else:
            tp = round(entry - tp_distance, 2)

    notes: list[str] = []
    if timing:
        notes.append(f"order={timing.get('order_type')}")
    if cost:
        notes.append(f"cost_ok={cost.get('cost_ok')}")

    return RiskGateResult(
        approved=True,
        reason=None,
        size=size,
        sl=sl,
        tp=tp,
        entry=entry,
        notes=notes,
    )


def apply(
    decision: SPKDecision,
    state: SharedState,
    settings: Settings | None = None,
) -> SPKDecision:
    """Stamp the decision with resolved size/SL/TP, or mark it vetoed.

    Mutates and returns ``decision`` for convenient chaining.
    """
    result = evaluate(decision, state, settings)
    if not result.approved:
        if decision.action != ACTION_HOLD:
            decision.hard_veto = True
            decision.veto_reason = result.reason or "risk gate rejected"
            log.info("risk gate blocked %s: %s", decision.action, decision.veto_reason)
        return decision

    decision.size = result.size
    decision.sl = result.sl
    decision.tp = result.tp
    if decision.entry is None:
        decision.entry = result.entry
    if result.notes:
        decision.soft_notes = [*decision.soft_notes, *result.notes]
    return decision
