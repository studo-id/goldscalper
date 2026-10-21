"""SPK weighted-voting engine.

Consensus score = Σ (vote_i × confidence_i × weight_i) over all signals.
The sign and magnitude map to an action via configurable thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.base import AgentSignal
from spk.decision import (
    ACTION_BUY,
    ACTION_HOLD,
    ACTION_SELL,
    STRENGTH_NONE,
    STRENGTH_NORMAL,
    STRENGTH_STRONG,
)


@dataclass(frozen=True)
class SPKThresholds:
    """Score thresholds mapping consensus to action/strength."""

    strong: float = 2.0
    weak: float = 0.5


@dataclass
class VotingResult:
    score: float = 0.0
    buy_score: float = 0.0
    sell_score: float = 0.0
    participation: int = 0
    agreement: float = 0.0  # 0..1 = |net| / gross
    division_scores: dict[str, float] = field(default_factory=dict)
    has_ping_pong_buy: bool = False
    has_ping_pong_sell: bool = False
    has_m1_sniper_buy: bool = False
    has_m1_sniper_sell: bool = False


def aggregate(signals: list[AgentSignal]) -> VotingResult:
    """Aggregate agent signals into a consensus result."""
    net = 0.0
    buy = 0.0
    sell = 0.0
    gross = 0.0
    participation = 0
    division_scores: dict[str, float] = {}

    for sig in signals:
        contribution = sig.score
        gross += abs(contribution)
        net += contribution
        if contribution > 0:
            buy += contribution
        elif contribution < 0:
            sell += -contribution
        if sig.vote != 0 and sig.confidence > 0:
            participation += 1
        division_scores[sig.division] = division_scores.get(sig.division, 0.0) + contribution

    agreement = (abs(net) / gross) if gross > 0 else 0.0
    has_pp_buy = any(
        isinstance(getattr(sig, "metadata", None), dict)
        and sig.metadata.get("ping_pong_side") == "BUY"
        for sig in signals
    )
    has_pp_sell = any(
        isinstance(getattr(sig, "metadata", None), dict)
        and sig.metadata.get("ping_pong_side") == "SELL"
        for sig in signals
    )
    has_m1_buy = any(
        getattr(sig, "agent_id", "") == "TF-M1-Sniper" and sig.vote > 0 and (sig.confidence or 0.0) >= 0.70
        for sig in signals
    )
    has_m1_sell = any(
        getattr(sig, "agent_id", "") == "TF-M1-Sniper" and sig.vote < 0 and (sig.confidence or 0.0) >= 0.70
        for sig in signals
    )
    return VotingResult(
        score=round(net, 4),
        buy_score=round(buy, 4),
        sell_score=round(sell, 4),
        participation=participation,
        agreement=round(agreement, 4),
        division_scores={k: round(v, 4) for k, v in division_scores.items()},
        has_ping_pong_buy=has_pp_buy,
        has_ping_pong_sell=has_pp_sell,
        has_m1_sniper_buy=has_m1_buy,
        has_m1_sniper_sell=has_m1_sell,
    )


def action_for_score(
    score: float,
    thresholds: SPKThresholds,
    result: VotingResult | None = None,
    reload_side: str | None = None,
    portfolio_state: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Map a consensus score to (action, strength) with dynamic confluence scaling.

    When multiple divisions (e.g. timeframe, structure, technical) actively agree
    on the direction, the trigger threshold dynamically softens (confluence discount),
    enabling aggressive, proactive entries. When only 1 lone agent votes, a higher bar
    is enforced to filter out single-candle noise. When Predator Reload is active
    immediately following a winning harvest, threshold softens for fast trend ride.
    Thresholds also dynamically modulate based on daily portfolio health and sprint target proximity.
    """
    a = abs(score)
    weak_threshold = thresholds.weak
    strong_threshold = thresholds.strong

    if result is not None and result.division_scores:
        # Count actively agreeing divisions with meaningful contribution (|score| >= 0.15)
        if score > 0:
            agreeing_divs = sum(1 for v in result.division_scores.values() if v >= 0.15)
        elif score < 0:
            agreeing_divs = sum(1 for v in result.division_scores.values() if v <= -0.15)
        else:
            agreeing_divs = 0

        # M1 Sniper Fast-Lane Trigger (Active High-Conviction M1 Rejection/Momentum Scalp):
        if (result.has_m1_sniper_buy and score > 0) or (result.has_m1_sniper_sell and score < 0):
            weak_threshold = max(0.35, thresholds.weak * 0.70)
            strong_threshold = max(1.2, thresholds.strong * 0.75)
        # Cylinder: Ping-Pong Sideways Rejection at support/resistance
        elif (result.has_ping_pong_buy and score > 0) or (result.has_ping_pong_sell and score < 0):
            weak_threshold = max(0.30, thresholds.weak * 0.60)
            strong_threshold = max(1.1, thresholds.strong * 0.70)
        # Cylinder 3: Predator Reload discount when momentum continuation is armed
        elif reload_side and ((reload_side == "BUY" and score > 0) or (reload_side == "SELL" and score < 0)):
            weak_threshold = max(0.35, thresholds.weak * 0.60)
            strong_threshold = max(1.2, thresholds.strong * 0.70)
        elif agreeing_divs >= 3:
            # Multi-division consensus (e.g. timeframe + technical + structure): ultra-fast entry!
            weak_threshold = max(0.40, thresholds.weak * 0.70)
            strong_threshold = max(1.5, thresholds.strong * 0.80)
        elif agreeing_divs >= 2:
            # 2 divisions agree: fast aggressive entry discount
            weak_threshold = max(0.45, thresholds.weak * 0.85)
            strong_threshold = max(1.5, thresholds.strong * 0.90)
        else:
            # Lone agent or single division: require reasonable evidence (calibrated from 0.85 to 0.55 for scalper)
            weak_threshold = max(0.55, thresholds.weak * 1.10)

    # Dynamic SPK Portfolio & Daily Target Modulation:
    if portfolio_state:
        pnl_pct = float(portfolio_state.get("daily_pnl_pct", 0.0) or 0.0)
        remaining_target = portfolio_state.get("remaining_target_usd")
        target_locked = bool(portfolio_state.get("daily_profit_locked", False))

        # 0. Target Accomplished / Capital Locked: Hold positions, no new speculative risks
        if target_locked or (remaining_target is not None and remaining_target <= 0.0):
            return ACTION_HOLD, STRENGTH_NONE

        # 1. Proportional Drawdown Gradient (Dynamic Defense Mode):
        # As drawdown deepens (pnl_pct < 0), progressively scale up consensus bar
        if pnl_pct < 0:
            drawdown_penalty = min(0.60, abs(pnl_pct) / 15.0)  # e.g., -3% -> +20%, -6% -> +40%
            weak_threshold *= (1.0 + drawdown_penalty)
            strong_threshold *= (1.0 + drawdown_penalty * 0.75)
        # 2. Growth Mode: in healthy daily profit (>= +3%), allow confident trend riders
        elif pnl_pct >= 3.0:
            strong_threshold *= 0.92

        # 3. Finish Line Proximity: When remaining daily target is within striking distance (<= $25)
        # Only accept high-confluence setups (raise entry bar) to guarantee a clean finish
        if remaining_target is not None and 0 < remaining_target <= 25.0:
            proximity_strictest = min(1.35, 1.0 + (25.0 - remaining_target) / 50.0)
            weak_threshold = max(weak_threshold, thresholds.weak * proximity_strictest)
            strong_threshold = max(strong_threshold, thresholds.strong * 1.05)

    # M1 Scalper Micro-Reversal Override:
    # When micro-structure (M1 & M5) is unambiguously bullish and M1 Sniper or Ping-Pong triggers a buy,
    # or unambiguously bearish and M1 Sniper or Ping-Pong triggers a sell,
    # prioritize the fresh micro scalping direction over lagging macro net score!
    m1_micro = portfolio_state.get("m1_micro_vote") if portfolio_state else None
    m5_micro = portfolio_state.get("m5_micro_vote") if portfolio_state else None

    if result is not None:
        if m1_micro == 1 and m5_micro == 1 and (result.has_m1_sniper_buy or result.has_ping_pong_buy):
            if result.buy_score >= weak_threshold:
                strength = STRENGTH_STRONG if result.buy_score >= strong_threshold else STRENGTH_NORMAL
                return ACTION_BUY, strength
        elif m1_micro == -1 and m5_micro == -1 and (result.has_m1_sniper_sell or result.has_ping_pong_sell):
            if result.sell_score >= weak_threshold:
                strength = STRENGTH_STRONG if result.sell_score >= strong_threshold else STRENGTH_NORMAL
                return ACTION_SELL, strength

    if a >= strong_threshold:
        strength = STRENGTH_STRONG
    elif a > weak_threshold:
        strength = STRENGTH_NORMAL
    else:
        return ACTION_HOLD, STRENGTH_NONE

    return (ACTION_BUY if score > 0 else ACTION_SELL), strength


def confidence_from(result: VotingResult, thresholds: SPKThresholds) -> float:
    """Derive a 0..1 confidence from magnitude and agreement.

    Magnitude is normalised against the strong threshold; agreement rewards
    one-sided consensus over internally conflicting signals.
    """
    magnitude = min(1.0, abs(result.score) / thresholds.strong) if thresholds.strong else 0.0
    # participation factor saturates at ~6 voters
    participation = min(1.0, result.participation / 6.0)
    raw = 0.6 * magnitude + 0.25 * result.agreement + 0.15 * participation
    return round(max(0.0, min(1.0, raw)), 4)
