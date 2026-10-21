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
    d1_macro_hard_veto_enabled: bool = False
    d1_macro_soft_penalty: float = 0.15
    counter_trend_defense_block_enabled: bool = False


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

    # --- Juggler & BizDev: HTF Counter-Trend Defense Protection ---
    # When portfolio is in DEFENSE mode (daily_pnl_pct < 0), counter-trend trading
    # against confirmed Higher Timeframe (H1 + D1) trends is strictly forbidden!
    # Eliminates catching falling knives in macro downtrends or shorting rockets in macro uptrends.
    daily_pnl_pct = float(getattr(state, "daily_pnl_pct", 0.0) or 0.0) if state else 0.0
    h1_sig = next((s for s in signals if s.agent_id == "TF-H1-Regime"), None)
    d1_sig = next((s for s in signals if s.agent_id == "TF-D1-Macro"), None)

    h1_bear = False
    if h1_sig is not None:
        h1_bear = (h1_sig.vote < 0 or h1_sig.veto == VETO_BUY or "BEARISH" in (h1_sig.reasoning or "").upper())
    elif state and state.flag("h1_vote") is not None and state.flag("h1_vote") < 0:
        h1_bear = True

    d1_bear = False
    if d1_sig is not None:
        d1_bear = (d1_sig.vote < 0 or d1_sig.veto == VETO_BUY or "BEARISH" in (d1_sig.reasoning or "").upper())

    macro_bearish = h1_bear and d1_bear

    h1_bull = False
    if h1_sig is not None:
        h1_bull = (h1_sig.vote > 0 or h1_sig.veto == VETO_SELL or "BULLISH" in (h1_sig.reasoning or "").upper())
    elif state and state.flag("h1_vote") is not None and state.flag("h1_vote") > 0:
        h1_bull = True

    d1_bull = False
    if d1_sig is not None:
        d1_bull = (d1_sig.vote > 0 or d1_sig.veto == VETO_SELL or "BULLISH" in (d1_sig.reasoning or "").upper())

    macro_bullish = h1_bull and d1_bull

    if p.counter_trend_defense_block_enabled and daily_pnl_pct < 0.0:
        if direction == ACTION_BUY and macro_bearish:
            return VetoResult(
                hard=True,
                reason="COUNTER_TREND_DEFENSE: Strictly prohibited from opening counter-trend BUY against confirmed H1/D1 bearish trend in Defense Mode",
                notes=["COUNTER_TREND:H1_D1_BEARISH:veto_buy"],
            )
        if direction == ACTION_SELL and macro_bullish:
            return VetoResult(
                hard=True,
                reason="COUNTER_TREND_DEFENSE: Strictly prohibited from opening counter-trend SELL against confirmed H1/D1 bullish trend in Defense Mode",
                notes=["COUNTER_TREND:H1_D1_BULLISH:veto_sell"],
            )
    elif macro_bearish and direction == ACTION_BUY:
        result.confidence_delta -= 0.40
        result.notes.append("Counter-trend BUY penalized against confirmed H1/D1 bearish macro trend (-0.40)")
    elif macro_bullish and direction == ACTION_SELL:
        result.confidence_delta -= 0.40
        result.notes.append("Counter-trend SELL penalized against confirmed H1/D1 bullish macro trend (-0.40)")

    for sig in signals:
        if sig.veto in (blocking_flag, VETO_ALL):
            if sig.veto == VETO_ALL:
                m1_active = any(
                    s.agent_id == "TF-M1-Sniper"
                    and s.confidence >= 0.65
                    and (s.vote > 0 if direction == ACTION_BUY else s.vote < 0)
                    for s in signals
                )
                if m1_active:
                    result.confidence_delta -= 0.15
                    result.notes.append(f"{sig.agent_id}:VETO_ALL demoted to soft penalty by active M1 Sniper trigger")
                    continue
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

                market_regime = state.extra.get("market_regime") if (state and hasattr(state, "extra") and isinstance(state.extra, dict)) else None

                # 1. CRITICAL ANTI-SUICIDE IN SIDEWAY REGIMES (Anti-Pucuk & Anti-Lembah):
                # In a SIDEWAY / range-bound market, S/R boundaries are BOUNCE WALLS, NOT breakout corridors!
                # Selling at the bottom (support floor) or buying at the top (resistance ceiling) is strictly forbidden.
                is_sideway = (
                    market_regime == "SIDEWAY"
                    or sideways_mode
                    or is_ping_pong
                    or (state and hasattr(state, "extra") and isinstance(state.extra, dict) and state.extra.get("sideways_range"))
                )
                if is_sideway and not any(s.agent_id == "TF-M1-Sniper" and s.confidence >= 0.75 for s in signals):
                    boundary_name = "SUPPORT FLOOR" if direction == ACTION_SELL else "RESISTANCE CEILING"
                    return VetoResult(
                        hard=True,
                        reason=f"HARD BARRIER (ANTI_SIDEWAY_TRAP): {sig.agent_id} blocked {direction} at {boundary_name} in SIDEWAY regime ({sig.reasoning})",
                        notes=[f"{sig.agent_id}:{sig.veto}:barrier_sideway_trap"],
                    )

                # 2. Finish Line Lockdown: Near daily sprint goal (remaining <= $20), strictly maintain hard barrier
                rem_target = (
                    state.extra.get("remaining_target_usd")
                    if (state and hasattr(state, "extra") and isinstance(state.extra, dict))
                    else None
                )
                daily_pnl_pct = float(getattr(state, "daily_pnl_pct", 0.0) or 0.0) if state else 0.0
                is_finish_line = rem_target is not None and 0 < rem_target <= 20.0
                if is_finish_line:
                    return VetoResult(
                        hard=True,
                        reason=f"HARD BARRIER (FINISH_LINE_LOCKDOWN): {sig.agent_id} blocked {direction} near target (${rem_target:.1f} remaining) ({sig.reasoning})",
                        notes=[f"{sig.agent_id}:{sig.veto}:barrier_finish_line"],
                    )

                # 3. Juggler Trend Continuation Override:
                # If Market Lifecycle is in active TRENDING expansion in this trade direction,
                # the S/R boundary is a continuation/breakout path, not a hard blocking barrier!
                if (
                    (direction == ACTION_SELL and market_regime == "TRENDING_BEAR")
                    or (direction == ACTION_BUY and market_regime == "TRENDING_BULL")
                ):
                    result.confidence_delta -= 0.10
                    result.notes.append(
                        f"Barrier {sig.agent_id} demoted for active trend continuation ({market_regime})"
                    )
                    continue

                # 4. Confluence count in candidate direction vs opposing direction
                spk_confluence_count = sum(
                    1 for s in signals
                    if (s.vote > 0 if direction == ACTION_BUY else s.vote < 0)
                )
                spk_opposing_count = sum(
                    1 for s in signals
                    if (s.vote < 0 if direction == ACTION_BUY else s.vote > 0)
                )
                has_clear_consensus = (
                    spk_confluence_count >= 5
                    and spk_confluence_count > spk_opposing_count
                )

                # 4. Dynamic demotion anchored to Juggler Portfolio State (Trending / Breakout markets)
                if has_clear_consensus:
                    # In Defense mode, scale penalty dynamically with drawdown
                    if daily_pnl_pct < 0.0:
                        pnl_mult = min(1.5, 1.0 + abs(daily_pnl_pct) / 20.0)
                        penalty = round(0.12 * pnl_mult, 4)
                        result.confidence_delta -= penalty
                        result.notes.append(
                            f"Barrier {sig.agent_id} demoted to soft penalty (-{penalty}) by SPK consensus "
                            f"({spk_confluence_count} confirming vs {spk_opposing_count} opposing, defense pnl={daily_pnl_pct:.1f}%)"
                        )
                        continue
                    else:
                        penalty = 0.10
                        result.confidence_delta -= penalty
                        result.notes.append(
                            f"Barrier {sig.agent_id} demoted to soft penalty (-{penalty}) by SPK consensus "
                            f"({spk_confluence_count} confirming vs {spk_opposing_count} opposing, growth/balanced)"
                        )
                        continue

                return VetoResult(
                    hard=True,
                    reason=f"HARD BARRIER: {sig.agent_id} blocked {direction} at key boundary ({sig.reasoning})",
                    notes=[f"{sig.agent_id}:{sig.veto}:barrier"],
                )

            is_tf_agent = (sig.division == "timeframe" or sig.agent_id.startswith("TF-"))
            is_analysis_agent = sig.division in ("structure", "technical", "timeframe", "fundamental")

            # CRITICAL ANTI-SUICIDE PROTECTION: Extreme Discount / Premium Valuation
            # In sideways markets or range conditions, selling at extreme discount (support floor)
            # or buying at extreme premium (resistance ceiling) is fatal and must NEVER be demoted!
            reason_upper = (sig.reasoning or "").upper()
            is_extreme_location = (
                (direction == ACTION_SELL and ("DISCOUNT" in reason_upper or "EXTREME_DISCOUNT" in reason_upper))
                or (direction == ACTION_BUY and ("PREMIUM" in reason_upper or "EXTREME_PREMIUM" in reason_upper))
            )
            if is_extreme_location:
                # D1 Macro Extreme Zones: For fast M1/M5 scalping, daily macro zones must NEVER
                # hard-paralyze entries unless explicitly configured. Demote to a soft confidence penalty!
                if (sig.agent_id == "TF-D1-Macro" or is_tf_agent) and not p.d1_macro_hard_veto_enabled:
                    result.confidence_delta -= p.d1_macro_soft_penalty
                    result.notes.append(
                        f"D1 Macro valuation softened to confidence penalty (-{p.d1_macro_soft_penalty:.2f}) ({sig.agent_id}:{sig.reasoning or sig.veto})"
                    )
                    continue

                return VetoResult(
                    hard=True,
                    reason=f"EXTREME BOUNDARY: {sig.agent_id} blocked {direction} at unfavorable valuation ({sig.reasoning or sig.veto})",
                    notes=[f"{sig.agent_id}:{sig.veto}:extreme_valuation"],
                )

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

    # --- Data-Driven Wave Capacity & Broken Wave Guard ---
    wave_engine = extra.get("wave_engine")
    if wave_engine is not None and direction in (ACTION_BUY, ACTION_SELL):
        wave_cap = wave_engine.evaluate_wave(state, candidate_direction=direction)
        extra["wave_capacity"] = wave_cap.to_dict()
        if not wave_cap.can_chain:
            return VetoResult(hard=True, reason=f"VETO_WAVE: {wave_cap.reason}")
        if wave_cap.capacity == "MATURE":
            result.confidence_delta -= 0.05
            result.notes.append(f"Wave is mature ({wave_cap.extension_atr:.1f}x ATR)")

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

    # Sideway Caution: Dynamic confidence penalty at channel boundaries based on HTF alignment
    if sideways_mode:
        sr_res = state.extra.get("sr_resistance")
        sr_sup = state.extra.get("sr_support")
        cur_p = state.bid or state.last_price()
        if cur_p is not None:
            h1_v = state.flag("h1_vote")
            htf_opp = (
                (direction == ACTION_BUY and h1_v is not None and h1_v < 0)
                or (direction == ACTION_SELL and h1_v is not None and h1_v > 0)
            )
            dyn_penalty = 0.40 if htf_opp else 0.20
            if direction == ACTION_BUY and sr_res is not None and cur_p >= (sr_res - 0.50):
                result.confidence_delta -= dyn_penalty
                result.notes.append(f"Sideway resistance ceiling caution (${cur_p:.1f} >= ${sr_res:.1f}, htf_opp={htf_opp}) -{dyn_penalty:.2f}")
            elif direction == ACTION_SELL and sr_sup is not None and cur_p <= (sr_sup + 0.50):
                result.confidence_delta -= dyn_penalty
                result.notes.append(f"Sideway support floor caution (${cur_p:.1f} <= ${sr_sup:.1f}, htf_opp={htf_opp}) -{dyn_penalty:.2f}")

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
