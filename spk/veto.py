"""SPK veto engine.

Two veto classes:

* **Hard veto** — blocks the trade entirely (e.g. a higher-timeframe agent
  explicitly blocks the direction, daily loss limit hit, news blackout).
* **Soft veto** — reduces confidence (e.g. HTF conflict, wide spread, thin
  liquidity).

Veto rules are deterministic and evaluated in the hot path (sub-millisecond).
No LLM inference is involved here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timezone

UTC = timezone.utc

from agents.base import AgentSignal
from agents.state import VETO_ALL, VETO_BUY, VETO_SELL, SharedState
from config.settings import settings as default_settings
from spk.decision import ACTION_BUY, ACTION_SELL


@dataclass
class VetoParams:
    """Tunable veto parameters (defaults reflect the agreed design)."""

    max_spread_points: int = 45
    htf_conflict_penalty: float = 0.30
    wide_spread_penalty: float = 0.20
    low_liquidity_penalty: float = 0.15
    min_confidence_floor: float = 0.0


@dataclass
class VetoResult:
    hard: bool = False
    reason: str | None = None
    confidence_delta: float = 0.0  # negative values reduce confidence
    notes: list[str] = field(default_factory=list)


def evaluate(
    signals: list[AgentSignal],
    state: SharedState,
    direction: str,
    params: VetoParams | None = None,
) -> VetoResult:
    """Evaluate hard and soft vetoes for a proposed trade direction.

    ``direction`` is one of :data:`spk.decision.ACTION_BUY` / ``ACTION_SELL``.
    """
    p = params or VetoParams()
    result = VetoResult()

    # --- Hard vetoes -------------------------------------------------------
    blocking_flag = VETO_BUY if direction == ACTION_BUY else VETO_SELL
    
    # Check for HTF deadlock: both VETO_BUY and VETO_SELL present among signals
    veto_flags = {sig.veto for sig in signals if sig.veto}
    htf_deadlock = (VETO_BUY in veto_flags and VETO_SELL in veto_flags)
    
    # Check if sideways / ping-pong pattern is active
    sideways_mode = state.flag("sideways_range", False) or state.flag("regime") == "SIDEWAYS"
    is_ping_pong = any(
        getattr(sig, "metadata", {}).get("ping_pong_side") == direction
        for sig in signals
    )

    for sig in signals:
        if sig.veto in (blocking_flag, VETO_ALL):
            if sig.veto == VETO_ALL:
                return VetoResult(
                    hard=True,
                    reason=f"HARD BARRIER: {sig.agent_id} blocked trade in M1 mid-range dead zone ({sig.reasoning})",
                    notes=[f"{sig.agent_id}:VETO_ALL:barrier"],
                )

            # Critical S/R Wall & Liquidity Sweep Protection (Hard Barrier)
            # High-confidence resistance/support rejection or BSL/SSL sweeps must NEVER be softened!
            is_sr_barrier = (
                (sig.confidence or 0.0) >= 0.70
                and sig.agent_id in ("Tech-SupportResistance", "Struct-Liquidity", "Tech-Pattern")
                and any(
                    kw in (sig.reasoning or "").lower()
                    for kw in ("resistance", "support", "bsl sweep", "ssl sweep", "rejection")
                )
            )
            if is_sr_barrier:
                if state and hasattr(state, "extra") and isinstance(state.extra, dict):
                    barrier_type = "RESISTANCE" if blocking_flag == VETO_BUY else "SUPPORT"
                    state.extra["active_sr_barrier"] = barrier_type
                    state.extra["active_sr_barrier_agent"] = sig.agent_id
                    state.extra["active_sr_barrier_reason"] = sig.reasoning

                # Juggler Trend Continuation Override:
                # If Market Lifecycle is in active TRENDING expansion in this trade direction,
                # the S/R boundary is a continuation/breakout path, not a hard blocking barrier!
                market_regime = state.extra.get("market_regime") if (state and hasattr(state, "extra") and isinstance(state.extra, dict)) else None
                if (
                    (direction == ACTION_SELL and market_regime == "TRENDING_BEAR")
                    or (direction == ACTION_BUY and market_regime == "TRENDING_BULL")
                ):
                    result.confidence_delta -= 0.10
                    result.notes.append(
                        f"Barrier {sig.agent_id} demoted for active trend continuation ({market_regime})"
                    )
                    continue

                # Juggler High-Confluence Breakout Override:
                # If SPK consensus has overwhelming multi-agent agreement (>= 18 confirming agents)
                # AND portfolio health is safe (daily_pnl_pct >= -1.0%),
                # the S/R boundary is treated as an active breakout rather than a hard block.
                spk_confluence_count = sum(
                    1 for s in signals
                    if (s.vote > 0 if direction == ACTION_BUY else s.vote < 0)
                )
                daily_pnl_pct = float(getattr(state, "daily_pnl_pct", 0.0) or 0.0)
                if spk_confluence_count >= 18 and daily_pnl_pct >= -1.0:
                    result.confidence_delta -= 0.15
                    result.notes.append(
                        f"Barrier {sig.agent_id} demoted to soft penalty by SPK consensus ({spk_confluence_count} confirming agents)"
                    )
                    continue

                return VetoResult(
                    hard=True,
                    reason=f"HARD BARRIER: {sig.agent_id} blocked {direction} at key boundary ({sig.reasoning})",
                    notes=[f"{sig.agent_id}:{sig.veto}:barrier"],
                )

            is_tf_agent = (sig.division == "timeframe" or sig.agent_id.startswith("TF-"))
            is_analysis_agent = sig.division in ("structure", "technical", "timeframe", "fundamental")

            # 1. During sideways/ping-pong conditions, HTF deadlock, or for analysis conflicts:
            # demote directional vetoes to soft confidence penalties so 37-agent consensus can scalp.
            if is_analysis_agent and (htf_deadlock or is_ping_pong or sideways_mode):
                result.confidence_delta -= p.htf_conflict_penalty
                result.notes.append(
                    f"Analysis veto demoted to soft penalty for sideways/ping-pong ({sig.agent_id}:{sig.veto})"
                )
                continue

            # 2. HTF Macro Directional De-escalation (H1, H4, D1, etc.):
            # For ultra-fast M1 scalping, macro HTF directional bias must NEVER hard-paralyze the bot!
            # Instead, it applies a calibrated confidence penalty (-0.30) so high-conviction scalps can proceed.
            if is_tf_agent:
                result.confidence_delta -= p.htf_conflict_penalty
                result.notes.append(
                    f"HTF macro veto softened to confidence penalty ({sig.agent_id}:{sig.veto})"
                )
                continue
            elif is_analysis_agent and sig.division in ("structure", "technical"):
                result.confidence_delta -= 0.20
                result.notes.append(
                    f"Structural veto softened to confidence penalty ({sig.agent_id}:{sig.veto})"
                )
                continue
            else:
                return VetoResult(
                    hard=True,
                    reason=f"{sig.agent_id} blocked {direction}: {sig.reasoning or sig.veto}",
                    notes=[f"{sig.agent_id}:{sig.veto}"],
                )

    if state.daily_loss_exceeded:
        return VetoResult(hard=True, reason="daily loss limit reached")
    if state.weekly_loss_exceeded:
        return VetoResult(hard=True, reason="weekly loss limit reached")
    if getattr(state, "daily_profit_locked", False):
        return VetoResult(hard=True, reason="daily profit target locked (capital secured)")

    extra = state.extra if hasattr(state, "extra") and isinstance(state.extra, dict) else {}
    if extra.get("last_tick_age_s") is not None and float(extra.get("last_tick_age_s", 0.0)) > 5.0:
        return VetoResult(hard=True, reason="tick feed stale (>5s)")
    if extra.get("mt5_connected") is False:
        return VetoResult(hard=True, reason="MT5 bridge disconnected")

    rem_target = (
        state.extra.get("remaining_target_usd")
        if hasattr(state, "extra") and isinstance(state.extra, dict)
        else None
    )
    if rem_target is not None and rem_target <= 0.0 and (state.daily_realized_pnl or 0.0) > 0:
        return VetoResult(hard=True, reason="daily sprint profit target achieved")

    if state.is_news_blackout():
        cur_news = state.extra.get("current_news")
        news_desc = f"news blackout: {cur_news.get('title')}" if cur_news else "news blackout window"
        return VetoResult(hard=True, reason=news_desc)

    # --- Institutional Session Clock Vetoes ---
    # Evaluated via state flags (set by runtime or test scenarios)
    if state.flag("london_open_freeze", False):
        return VetoResult(
            hard=True,
            reason="LONDON_OPEN_OBSERVATION (08:00-08:15 UTC freeze, awaiting M15 candle close)",
        )

    if state.flag("session_hard_cutoff", False):
        return VetoResult(
            hard=True,
            reason="SESSION_HARD_CUTOFF_1530_UTC (no new intraday entries allowed after 15:30 UTC)",
        )

    # --- Micro-Exhaustion Pullback Guard (AcengGold-grade) ---
    m1_micro = extra.get("m1_micro_vote")
    m5_micro = extra.get("m5_micro_vote")
    if m1_micro is not None and m5_micro is not None:
        if direction == ACTION_SELL and m1_micro == 1 and m5_micro == 1:
            return VetoResult(
                hard=True,
                reason="REJECTED_MICRO_EXHAUSTION: M5 dan M1 keduanya berstatus BULLISH (terjadi pantulan di micro-structure)",
            )
        if direction == ACTION_BUY and m1_micro == -1 and m5_micro == -1:
            return VetoResult(
                hard=True,
                reason="REJECTED_MICRO_EXHAUSTION: M5 dan M1 keduanya berstatus BEARISH (terjadi penolakan di micro-structure)",
            )

    if state.flag("d1_extreme_zone", False):
        if htf_deadlock or is_ping_pong or sideways_mode:
            result.confidence_delta -= p.htf_conflict_penalty
            result.notes.append("D1 extreme zone demoted to soft penalty for sideways ping-pong")
        else:
            return VetoResult(hard=True, reason="D1 extreme premium/discount zone")

    if state.flag("h4_block_touch", False):
        if htf_deadlock or is_ping_pong or sideways_mode:
            result.confidence_delta -= p.htf_conflict_penalty
            result.notes.append("H4 supply/demand block touch demoted to soft penalty for sideways ping-pong")
        else:
            return VetoResult(hard=True, reason="H4 supply/demand block touch against direction")

    # Sideway Caution: Soft confidence penalty at channel boundaries without hard deadlock
    if sideways_mode:
        sr_res = state.extra.get("sr_resistance")
        sr_sup = state.extra.get("sr_support")
        cur_p = state.bid or state.last_price()
        if cur_p is not None:
            if direction == ACTION_BUY and sr_res is not None and cur_p >= sr_res:
                result.confidence_delta -= 0.25
                result.notes.append(f"Sideway resistance ceiling caution (${cur_p:.1f} >= ${sr_res:.1f})")
            elif direction == ACTION_SELL and sr_sup is not None and cur_p <= sr_sup:
                result.confidence_delta -= 0.25
                result.notes.append(f"Sideway support floor caution (${cur_p:.1f} <= ${sr_sup:.1f})")

    # --- Soft vetoes -------------------------------------------------------
    # Dynamic Soft Veto Penalty Multiplier based on Portfolio Drawdown
    daily_pnl_pct = float(getattr(state, "daily_pnl_pct", 0.0) or 0.0)
    pnl_penalty_mult = min(1.50, 1.0 + abs(daily_pnl_pct) / 12.0) if daily_pnl_pct < 0 else 1.0

    h1_vote = state.flag("h1_vote")
    htf_against = (
        (direction == ACTION_BUY and h1_vote is not None and h1_vote < 0)
        or (direction == ACTION_SELL and h1_vote is not None and h1_vote > 0)
    )
    if htf_against:
        htf_penalty = round(p.htf_conflict_penalty * pnl_penalty_mult, 4)
        result.confidence_delta -= htf_penalty
        result.notes.append(
            f"HTF conflict (H1 vote={h1_vote} vs {direction}) -{htf_penalty:.2f}"
        )

    if state.spread_points is not None and state.spread_points > p.max_spread_points:
        spread_penalty = round(p.wide_spread_penalty * pnl_penalty_mult, 4)
        result.confidence_delta -= spread_penalty
        result.notes.append(
            f"wide spread ({state.spread_points}>{p.max_spread_points}) "
            f"-{spread_penalty:.2f}"
        )

    if state.is_low_liquidity():
        liq_penalty = round(p.low_liquidity_penalty * pnl_penalty_mult, 4)
        result.confidence_delta -= liq_penalty
        result.notes.append(f"low liquidity ({state.session}) -{liq_penalty:.2f}")

    # Finish Line Friction Protection: When within $15 of daily target, penalize even moderate spreads
    if rem_target is not None and 0 < rem_target <= 15.0:
        if state.spread_points is not None and state.spread_points > p.max_spread_points * 0.75:
            result.confidence_delta -= 0.15
            result.notes.append(f"finish line spread caution ({state.spread_points}pt)")

    result.confidence_delta = round(max(-1.0, result.confidence_delta), 4)
    return result
