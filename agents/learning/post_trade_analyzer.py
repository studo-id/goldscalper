"""Post-trade analyzer → Lesson Cards.

Turns a closed trade plus its decision context into a structured
:class:`LessonCard`: what happened, why (best-effort root cause), and what to
do differently. Persisted to ``trade_lessons`` and fed to the bandit/pattern
library.

Deterministic heuristics only; no LLM in this path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from config.logging import get_logger

log = get_logger("learning.post_trade")

OUTCOME_WIN = "win"
OUTCOME_LOSS = "loss"
OUTCOME_BREAKEVEN = "breakeven"

CAUSE_CONFIRMED = "signal_confirmed"
CAUSE_ADVERSE = "adverse_move"
CAUSE_SPREAD = "spread_slippage"
CAUSE_REGIME = "regime_mismatch"
CAUSE_PREMATURE = "premature_exit"
CAUSE_NEUTRAL = "neutral"


@dataclass
class LessonCard:
    """A single post-trade lesson."""

    trade_id: str | None
    regime: str | None
    outcome: str
    root_cause: str
    action: str
    score: float
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_repo_fields(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def outcome_from_pnl(pnl: float, breakeven_band: float = 0.0) -> str:
    if pnl > breakeven_band:
        return OUTCOME_WIN
    if pnl < -breakeven_band:
        return OUTCOME_LOSS
    return OUTCOME_BREAKEVEN


def analyze(
    trade: dict[str, Any],
    context: dict[str, Any] | None = None,
    *,
    spread_limit: int = 45,
    min_hold_seconds: int = 5,
) -> LessonCard:
    """Build a :class:`LessonCard` from a closed trade + context.

    ``trade`` keys: ``id``/``trade_id``, ``pnl``, ``pips``, ``duration_s``,
    ``direction``, ``symbol``. ``context`` may include ``regime``,
    ``spread_points``, ``division_scores``, ``risk_amount``.
    """
    ctx = context or {}
    trade_id = trade.get("id") or trade.get("trade_id")
    pnl = float(trade.get("pnl", 0.0) or 0.0)
    regime = ctx.get("regime") or trade.get("regime")
    duration = float(trade.get("duration_s", 0.0) or 0.0)
    spread = ctx.get("spread_points")

    outcome = outcome_from_pnl(pnl)
    risk_amount = float(ctx.get("risk_amount") or 0.0)
    score = (pnl / risk_amount) if risk_amount else (1.0 if pnl > 0 else -1.0 if pnl < 0 else 0.0)

    tags: list[str] = [outcome]
    if regime:
        tags.append(f"regime:{regime}")

    if outcome == OUTCOME_WIN:
        root_cause = CAUSE_CONFIRMED
        action = "keep weight; reinforce setup"
    elif outcome == OUTCOME_BREAKEVEN:
        root_cause = CAUSE_NEUTRAL
        action = "hold; no weight change"
    else:
        if spread is not None and spread > spread_limit:
            root_cause = CAUSE_SPREAD
            action = "widen spread filter / avoid entry in thin book"
            tags.append("cost")
        elif regime == "range":
            root_cause = CAUSE_REGIME
            action = "reduce trend weight in range regime"
            tags.append("regime")
        elif 0 < duration < min_hold_seconds:
            root_cause = CAUSE_PREMATURE
            action = "review entry timing; avoid immediate reversal stops"
            tags.append("timing")
        else:
            root_cause = CAUSE_ADVERSE
            action = "reduce failing agent weight"

    card = LessonCard(
        trade_id=trade_id,
        regime=regime,
        outcome=outcome,
        root_cause=root_cause,
        action=action,
        score=round(score, 4),
        tags=tags,
        metadata={
            "direction": trade.get("direction"),
            "symbol": trade.get("symbol"),
            "pnl": pnl,
            "pips": trade.get("pips"),
            "duration_s": duration,
            "spread_points": spread,
        },
    )
    log.debug("lesson %s: %s/%s", trade_id, outcome, root_cause)
    return card


__all__ = [
    "LessonCard",
    "analyze",
    "outcome_from_pnl",
    "OUTCOME_WIN",
    "OUTCOME_LOSS",
    "OUTCOME_BREAKEVEN",
    "CAUSE_CONFIRMED",
    "CAUSE_ADVERSE",
    "CAUSE_SPREAD",
    "CAUSE_REGIME",
    "CAUSE_PREMATURE",
    "CAUSE_NEUTRAL",
]
