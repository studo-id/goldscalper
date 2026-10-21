"""Position manager.

Applies the exit playbook to open positions: break-even, partial take-profit,
ATR/R trailing stop, and a hard time-stop. All mutations go through the MT5
client so the same logic works against the mock, native, or bridge clients.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agents.state import UTC, utcnow
from config.logging import get_logger
from config.settings import Settings
from config.settings import settings as default_settings
from core.clock import is_overnight_flat_window
from core.mt5_connector import MT5Client, Position

log = get_logger("execution.position_manager")

__all__ = ["PositionState", "PositionManager"]


@dataclass
class PositionState:
    """Per-ticket bookkeeping the manager needs to manage exits."""

    ticket: int
    entry: float
    initial_sl: float | None
    r_distance: float
    partial_taken: bool = False
    opened_at: datetime | None = None


def evaluate_multi_tf_watchdogs(pos_direction: str, context: dict[str, Any] | None) -> dict[str, Any]:
    """
    Multi-Timeframe Watchdog (Satpam Bertingkat):
      - Satpam Layer 1 (M1 Micro / Sniper): TF-M1-Sniper, Tech-EMA-Cross, Tech-RSI-Stoch
      - Satpam Layer 2 (M5 Swing Structure): TF-M5-Inspector, Struct-MarketStructure
      - Satpam Layer 3 (HTF Trend & Liquidity): TF-M15-Liquidity, TF-M30-Momentum, TF-H1-Regime, TF-H4-Structure

    Returns alignment metrics, verdicts, time-extension permissions, and invalidation alerts:
      {
        "m1": {"score": float, "verdict": "SUPPORTING"|"OPPOSING"|"NEUTRAL", "opposing_conf": float},
        "m5": {"score": float, "verdict": "SUPPORTING"|"OPPOSING"|"NEUTRAL", "opposing_conf": float},
        "htf": {"score": float, "verdict": "SUPPORTING"|"OPPOSING"|"NEUTRAL", "supporting": list, "opposing": list},
        "can_extend_time": bool,
        "invalidation_alert": bool,
      }
    """
    default_res: dict[str, Any] = {
        "m1": {"score": 0.0, "verdict": "NEUTRAL", "opposing_conf": 0.0},
        "m5": {"score": 0.0, "verdict": "NEUTRAL", "opposing_conf": 0.0},
        "htf": {"score": 0.0, "verdict": "NEUTRAL", "supporting": [], "opposing": []},
        "can_extend_time": False,
        "invalidation_alert": False,
    }
    if not context:
        return default_res

    if "watchdogs" in context and isinstance(context["watchdogs"], dict):
        res = dict(default_res)
        res.update(context["watchdogs"])
        return res

    decision = context.get("decision")
    if not decision or not getattr(decision, "votes", None):
        return default_res

    dir_upper = pos_direction.upper()
    pos_vote = 1 if dir_upper == "BUY" else -1

    m1_weights = {"TF-M1-Sniper": 2.0, "Tech-EMA-Cross": 1.0, "Tech-RSI-Stoch": 1.0}
    m5_weights = {"TF-M5-Inspector": 2.5, "Struct-MarketStructure": 2.0}
    htf_weights = {
        "TF-H4-Structure": 2.5,
        "TF-H1-Regime": 2.5,
        "TF-M30-Momentum": 1.5,
        "TF-M15-Liquidity": 1.5,
    }

    m1_align = 0.0
    m1_weight = 0.0
    m1_opp_conf = 0.0

    m5_align = 0.0
    m5_weight = 0.0
    m5_opp_conf = 0.0

    htf_align = 0.0
    htf_weight = 0.0
    htf_supp: list[str] = []
    htf_opp: list[str] = []

    for signal in decision.votes:
        agent_id = getattr(signal, "agent_id", "")
        vote = getattr(signal, "vote", 0)
        conf = float(getattr(signal, "confidence", 0.5) or 0.5)
        is_align = (vote > 0 and pos_vote > 0) or (vote < 0 and pos_vote < 0)
        is_oppose = (vote > 0 and pos_vote < 0) or (vote < 0 and pos_vote > 0)

        if agent_id in m1_weights:
            w = m1_weights[agent_id]
            m1_weight += w
            if is_align:
                m1_align += w * conf
            elif is_oppose:
                m1_align -= w * conf
                m1_opp_conf = max(m1_opp_conf, conf)

        if agent_id in m5_weights:
            w = m5_weights[agent_id]
            m5_weight += w
            if is_align:
                m5_align += w * conf
            elif is_oppose:
                m5_align -= w * conf
                m5_opp_conf = max(m5_opp_conf, conf)

        if agent_id in htf_weights:
            w = htf_weights[agent_id]
            htf_weight += w
            if is_align:
                htf_align += w * conf
                htf_supp.append(f"{agent_id}(conf={conf:.2f})")
            elif is_oppose:
                htf_align -= w * conf
                htf_opp.append(f"{agent_id}(conf={conf:.2f})")

    m1_score = round(m1_align / max(1.0, m1_weight), 2) if m1_weight > 0 else 0.0
    m1_verdict = "SUPPORTING" if m1_score >= 0.20 else ("OPPOSING" if m1_score <= -0.20 else "NEUTRAL")

    m5_score = round(m5_align / max(1.0, m5_weight), 2) if m5_weight > 0 else 0.0
    m5_verdict = "SUPPORTING" if m5_score >= 0.20 else ("OPPOSING" if m5_score <= -0.20 else "NEUTRAL")

    htf_score = round(htf_align / max(1.0, htf_weight), 2) if htf_weight > 0 else 0.0
    htf_verdict = "SUPPORTING" if htf_score >= 0.20 else ("OPPOSING" if htf_score <= -0.20 else "NEUTRAL")

    # Time extension permission: HTF is supporting and M5 structure has not broken against us
    can_extend_time = (htf_verdict == "SUPPORTING" and m5_verdict != "OPPOSING")

    # Invalidation alert:
    # CRITICAL HARMONIZATION: If HTF (H1, H4) is actively SUPPORTING our trade, a minor 10-20 pip pullback
    # on M1/M5 is expected noise. DO NOT trigger early invalidation panic into a supporting HTF trend!
    if htf_verdict == "SUPPORTING":
        invalidation_alert = False
    else:
        # 1. Primary: M1 and M5 both oppose our position.
        # 2. Strong M1 Oppose: If M1 is strongly opposing with high conviction (opposing_conf >= 0.70)
        #    and M5 is not actively supporting (i.e. M5 is NEUTRAL or OPPOSING), alert to prevent ballooning drawdown.
        invalidation_alert = (
            (m1_verdict == "OPPOSING" and m5_verdict == "OPPOSING")
            or (m1_verdict == "OPPOSING" and m1_opp_conf >= 0.70 and m5_verdict != "SUPPORTING")
        )

    return {
        "m1": {"score": m1_score, "verdict": m1_verdict, "opposing_conf": m1_opp_conf},
        "m5": {"score": m5_score, "verdict": m5_verdict, "opposing_conf": m5_opp_conf},
        "htf": {"score": htf_score, "verdict": htf_verdict, "supporting": htf_supp, "opposing": htf_opp},
        "can_extend_time": can_extend_time,
        "invalidation_alert": invalidation_alert,
    }


def evaluate_htf_reversal_bias(pos_direction: str, context: dict[str, Any] | None) -> dict[str, Any]:
    """Compatibility wrapper returning HTF bias dict."""
    return evaluate_multi_tf_watchdogs(pos_direction, context)["htf"]


@dataclass
class PositionManager:
    client: MT5Client
    settings: Settings = field(default_factory=lambda: default_settings)
    notifier: object | None = None

    def __post_init__(self) -> None:
        self._states: dict[int, PositionState] = {}
        self._basket_peak_profit: dict[str, float] = {}

    def track(self, pos: Position) -> PositionState:
        state = self._states.get(pos.ticket)
        if state is None:
            r = abs(pos.price_open - pos.sl) if pos.sl else 0.0
            state = PositionState(
                ticket=pos.ticket,
                entry=pos.price_open,
                initial_sl=pos.sl,
                r_distance=r,
                opened_at=pos.time or utcnow(),
            )
            self._states[pos.ticket] = state
        return state

    def untrack(self, ticket: int) -> None:
        self._states.pop(ticket, None)

    def _profit_distance(self, pos: Position, price: float) -> float:
        return (price - pos.price_open) if pos.is_long else (pos.price_open - price)

    async def manage(
        self,
        pos: Position,
        price: float,
        *,
        now: datetime | None = None,
        atr: float | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        """Return the list of actions taken for this position."""
        s = self.settings
        state = self.track(pos)
        moment = now or utcnow()
        actions: list[str] = []
        ctx = context or {}
        is_in_rescue_basket = bool(ctx.get("in_rescue_basket", False))
        watchdogs = evaluate_multi_tf_watchdogs(pos.side, ctx)
        htf_bias = watchdogs["htf"]

        held = (moment - state.opened_at).total_seconds() if state.opened_at is not None else 0.0

        # Smart Multi-Timeframe Watchdog Time Stop (Menggantikan 900s dumb timer)
        # Standalone positions only; rescue baskets are managed collectively via manage_basket
        max_hold = s.max_hold_seconds
        if not is_in_rescue_basket and state.opened_at is not None and held >= max_hold:
            can_extend = s.watchdog_enabled and watchdogs["can_extend_time"]
            extended_limit = max_hold + getattr(s, "watchdog_time_extension_seconds", 300)
            if can_extend and held < extended_limit:
                log.info(
                    "JUGGLER WATCHDOG TIME EXTENSION: Holding ticket %s (held %ds < %ds) — Satpam M5/HTF confirms structural support (%s)",
                    pos.ticket,
                    int(held),
                    extended_limit,
                    htf_bias["supporting"],
                )
            else:
                log.info(
                    "JUGGLER WATCHDOG TIME STOP: Closing ticket %s (held %ds >= %ds, can_extend=%s, htf=%s, m5=%s)",
                    pos.ticket,
                    int(held),
                    max_hold,
                    can_extend,
                    htf_bias["verdict"],
                    watchdogs["m5"]["verdict"],
                )
                await self.client.close_position(pos.ticket, price=price)
                self.untrack(pos.ticket)
                actions.append("time_stop")
                return actions

        # Institutional Overnight Flat Guard (Close intraday trades before rollover/weekend gap)
        if s.overnight_flat_utc_enabled and is_overnight_flat_window(moment):
            utc_dt = moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
            log.warning(
                "OVERNIGHT FLAT CUTOFF: Closing ticket %s at %s UTC (%s) to prevent rollover/weekend gap risk",
                pos.ticket, utc_dt.strftime("%H:%M"), utc_dt.strftime("%A"),
            )
            await self.client.close_position(pos.ticket, price=price)
            self.untrack(pos.ticket)
            actions.append("overnight_flat_cutoff")
            return actions

        # --- RESCUE BASKET UNITY SHIELD ---
        # When this ticket is part of an active multi-layer rescue basket (averaging down),
        # ALL exit decisions (cutloss, duration cuts, breakeven, trailing, TP, salvage)
        # MUST BE 100% EXCLUSIVELY managed collectively by manage_basket().
        # Cutting or closing individual legs in isolation destroys the rescue math,
        # breaks wave engine continuity, and strands the counterpart position!
        if is_in_rescue_basket:
            log.debug(
                "RESCUE BASKET SHIELD: Ticket %s (%s %.2f, pnl=%.2f) delegated exclusively to manage_basket()",
                pos.ticket,
                pos.side,
                pos.volume,
                float(pos.profit or 0.0),
            )
            return actions

        # --- THE JUGGLER: Dynamic Anti-Bleeding & In-Flight Reversal Matrix ---
        if s.juggler_enabled:
            current_loss = float(pos.profit or 0.0)
            live_avg_win = float(ctx.get("live_avg_win", 0.0) or 0.0)

            # 1. Base Clamp: Anchored to live average win or configured hard clamp ($7.00)
            base_clamp = max(s.hard_loss_clamp_usd, round(live_avg_win * 1.25, 2) if live_avg_win >= 2.0 else s.hard_loss_clamp_usd)
            # STRICT HARD CEILING: Clamp loss CANNOT balloon out of proportion!
            # Maximum loss allowed per scalper trade is capped strictly at 1.35x hard_loss_clamp_usd (max $8.50 - $9.50).
            max_clamp_ceiling = round(s.hard_loss_clamp_usd * 1.35, 2)
            effective_clamp_usd = min(base_clamp, max_clamp_ceiling)

            # 2. Phase 0: Noise & M1 Candle Formation Grace Period (0 - 60s)
            # Strictly PROTECT unclosed M1 candle wicks (< 60s). Allow Rescue Layer 2 (>= 20 pips) to operate!
            # Never cut early unless true runaway black-swan emergency gap (>= 45-50 pips / $35+)
            min_hold = getattr(s, "watchdog_min_hold_seconds", 60)
            catastrophic_gap_usd = max(35.0, round(pos.volume * 4.50 * 100.0, 2))
            if held < min_hold and current_loss > -catastrophic_gap_usd:
                pass  # Grace period: allow 1 full M1 candle (60s) to form cleanly without wick panic

            elif held < min_hold and current_loss <= -catastrophic_gap_usd:
                log.warning(
                    "JUGGLER CATASTROPHIC GAP CUT: Cutting ticket %s (%s %.2f, loss=%.2f <= -$%.2f flash breach within %ds)",
                    pos.ticket,
                    pos.side,
                    pos.volume,
                    current_loss,
                    catastrophic_gap_usd,
                    int(held),
                )
                await self.client.close_position(pos.ticket, price=price)
                self.untrack(pos.ticket)
                actions.append("juggler_catastrophic_gap_cut")
                return actions

            # 3. Phase 1: Satpam M1/M5 Early Invalidation Cut (Cut Loss Dini setelah 1 Candle M1 Close)
            elif (
                s.watchdog_early_invalidation_enabled
                and held >= min_hold
                and current_loss <= -max(4.0, round(effective_clamp_usd * s.watchdog_early_loss_ratio, 2))
                and watchdogs["invalidation_alert"]
            ):
                log.warning(
                    "JUGGLER WATCHDOG EARLY INVALIDATION CUT: Cutting ticket %s (%s %.2f, loss=%.2f <= -$%.2f) — Satpam M1/M5 adverse signal (M1=%s, M5=%s)",
                    pos.ticket,
                    pos.side,
                    pos.volume,
                    current_loss,
                    round(effective_clamp_usd * s.watchdog_early_loss_ratio, 2),
                    watchdogs["m1"]["verdict"],
                    watchdogs["m5"]["verdict"],
                )
                await self.client.close_position(pos.ticket, price=price)
                self.untrack(pos.ticket)
                actions.append("watchdog_early_invalidation_cut")
                return actions

            # 4. Phase 2: HTF Trend Breakdown (Early Cut — Do NOT Hope!)
            # If floating loss >= 65% of clamp AND Higher Timeframes (H4/H1/M30/M15) are actively opposing us:
            is_htf_supporting = htf_bias.get("verdict") in ("SUPPORTING", "HTF_SUPPORTING")
            is_htf_opposing = htf_bias.get("verdict") in ("OPPOSING", "HTF_OPPOSING")

            if (
                held >= min_hold
                and current_loss <= -(effective_clamp_usd * 0.65)
                and is_htf_opposing
            ):
                log.warning(
                    "JUGGLER HTF BREAKDOWN CUT: Ticket %s (%s %.2f, loss=%.2f <= -$%.2f) — HTF scouts opposing: %s",
                    pos.ticket,
                    pos.side,
                    pos.volume,
                    current_loss,
                    round(effective_clamp_usd * 0.65, 2),
                    htf_bias["opposing"],
                )
                await self.client.close_position(pos.ticket, price=price)
                self.untrack(pos.ticket)
                actions.append("juggler_htf_breakdown_cut")
                return actions

            # 5. Phase 3: Dynamic Hard Clamp & HTF Reversal Shield
            elif s.hard_loss_clamp_enabled and held >= min_hold and current_loss <= -abs(effective_clamp_usd):
                # When in an active multi-layer rescue basket, delegate loss management to manage_basket().
                # Do NOT cut Layer 1 individually, as it breaks basket unity and strands the recovery position!
                is_in_rescue_basket = bool(ctx.get("in_rescue_basket", False))
                if is_in_rescue_basket:
                    pass  # Collective basket management takes precedence
                else:
                    # When HTF (H4/H1/M30/M15) or Satpam M5 supports the trade, grant reversal breathing room:
                    htf_reversal_clamp = max(16.0, round(effective_clamp_usd * 2.25, 2), round(pos.volume * 3.50 * 100.0, 2))
                    is_m5_supporting = watchdogs.get("m5", {}).get("verdict") in ("SUPPORTING", "HTF_SUPPORTING")
                    # M5 Pattern Reversal Hold: allow up to 90s for M5 candle to complete reversal
                    can_reversal_hold = is_htf_supporting or (is_m5_supporting and held < 90)
                    reversal_clamp = htf_reversal_clamp if is_htf_supporting else round(effective_clamp_usd * 1.40, 2)

                    if can_reversal_hold and current_loss > -reversal_clamp:
                        # Allow trend continuation / reversal room while structure is healthy
                        pass
                    else:
                        clamp_reason = "HTF_EXHAUSTED" if is_htf_supporting else ("M5_EXHAUSTED" if is_m5_supporting else htf_bias.get("verdict", "NEUTRAL"))
                        log.warning(
                            "JUGGLER DYNAMIC CLAMP: Cutting ticket %s (%s %.2f, loss=%.2f <= -$%.2f [HTF=%s (%s), avg_win $%.2f])",
                            pos.ticket,
                            pos.side,
                            pos.volume,
                            current_loss,
                            effective_clamp_usd if not can_reversal_hold else reversal_clamp,
                            htf_bias.get("verdict"),
                            clamp_reason,
                            live_avg_win,
                        )
                        await self.client.close_position(pos.ticket, price=price)
                        self.untrack(pos.ticket)
                        actions.append("juggler_dynamic_clamp")
                        return actions

            # 6. Phase 4: Duration Stagnation Cut (90s - 150s with no reversal momentum)
            elif state.opened_at is not None and held >= 90:
                duration_loss_limit = max(2.50, round(effective_clamp_usd * 0.60, 2))
                if (
                    current_loss <= -duration_loss_limit
                    and htf_bias["verdict"] != "HTF_SUPPORTING"
                    and (watchdogs["m1"]["verdict"] == "OPPOSING" or watchdogs["m5"]["verdict"] == "OPPOSING")
                ):
                    log.info(
                        "JUGGLER DURATION-LOSS CUT: Ticket %s held %ds with loss=%.2f <= -$%.2f (momentum stalled)",
                        pos.ticket,
                        int(held),
                        current_loss,
                        duration_loss_limit,
                    )
                    await self.client.close_position(pos.ticket, price=price)
                    self.untrack(pos.ticket)
                    actions.append("juggler_duration_loss_cut")
                    return actions

            # 7. Phase 5: Time-Decay Loss Cut (>180s)
            elif state.opened_at is not None and held >= s.loss_time_decay_seconds:
                if current_loss <= -abs(s.loss_time_decay_min_loss_usd):
                    log.info(
                        "JUGGLER TIME-DECAY CUT: Cutting stalled losing ticket %s (held %ds, loss=%.2f <= -$%.2f)",
                        pos.ticket,
                        int(held),
                        current_loss,
                        s.loss_time_decay_min_loss_usd,
                    )
                    await self.client.close_position(pos.ticket, price=price)
                    self.untrack(pos.ticket)
                    actions.append("juggler_time_decay_cut")
                    return actions

        # --- THE JUGGLER: Dynamic Take-Profit & Target-Proximity Harvest ---
        if state.opened_at is not None:
            current_profit = float(pos.profit or 0.0)
            remaining_target_usd = ctx.get("remaining_target_usd")

            # 4. Target-Proximity Harvest: When close to daily sprint goal, harvest instantly!
            if (
                s.juggler_enabled
                and remaining_target_usd is not None
                and remaining_target_usd > 0
                and current_profit >= max(1.50, remaining_target_usd * 0.35)
            ):
                log.info(
                    "JUGGLER GOAL PROXIMITY TP: Closing ticket %s (profit=+$%.2f covers %.1f%% of remaining goal $%.2f)",
                    pos.ticket,
                    current_profit,
                    (current_profit / remaining_target_usd * 100.0),
                    remaining_target_usd,
                )
                await self.client.close_position(pos.ticket, price=price)
                self.untrack(pos.ticket)
                actions.append("target_proximity_tp")
                return actions

            # 5. Dynamic Risk-Free Fast Break-Even Lock (BEP+):
            # When part of a multi-layer rescue basket, bypass individual BEP!
            # Premature BEP exit on Layer 2 strands Layer 1 in drawdown. Basket exits collectively via manage_basket().
            is_in_rescue_basket = bool(ctx.get("in_rescue_basket", False))
            if not is_in_rescue_basket:
                be_sl = round(state.entry + 0.10 if pos.is_long else state.entry - 0.10, 2)
                be_trigger_pips = getattr(s, "fast_breakeven_pips", 12.0)
                be_trigger_usd = max(1.80, round(pos.volume * (be_trigger_pips / 100.0) * 100.0, 2))
                if current_profit >= be_trigger_usd:
                    if pos.is_long and (pos.sl is None or pos.sl < be_sl):
                        await self.client.modify_position(pos.ticket, sl=be_sl, tp=pos.tp)
                        pos.sl = be_sl
                        actions.append("breakeven_locked")
                    elif not pos.is_long and (pos.sl is None or pos.sl > be_sl):
                        await self.client.modify_position(pos.ticket, sl=be_sl, tp=pos.tp)
                        pos.sl = be_sl
                        actions.append("breakeven_locked")

            # 6. Solid Runner Harvest (Instant at Any Time):
            # When price spikes into a solid runner profit (>= $7.50 or 1.25x avg win), harvest IMMEDIATELY!
            live_avg_win = float(ctx.get("live_avg_win", 0.0) or 0.0)
            runner_target = max(7.50, round(live_avg_win * 1.25, 2)) if live_avg_win >= 2.0 else 7.50
            if s.juggler_enabled and current_profit >= runner_target:
                log.info(
                    "JUGGLER RUNNER HARVEST: Ticket %s held %ds with solid profit=+$%.2f >= $%.2f",
                    pos.ticket,
                    int(held),
                    current_profit,
                    runner_target,
                )
                await self.client.close_position(pos.ticket, price=price)
                self.untrack(pos.ticket)
                actions.append("juggler_runner_harvest")
                return actions

            # 7. Defensive Momentum Harvest (Held >= 90s):
            # If position held >= 90s and HTF opposes, harvest defensively (current_profit >= $3.50)
            if s.juggler_enabled and held >= 90:
                is_htf_opposing_harvest = htf_bias.get("verdict") in ("OPPOSING", "HTF_OPPOSING")
                if is_htf_opposing_harvest and current_profit >= 3.50:
                    log.info(
                        "JUGGLER HTF DEFENSIVE HARVEST: Ticket %s held %ds, profit=+$%.2f with HTF opposing: %s",
                        pos.ticket,
                        int(held),
                        current_profit,
                        htf_bias.get("opposing", []),
                    )
                    await self.client.close_position(pos.ticket, price=price)
                    self.untrack(pos.ticket)
                    actions.append("juggler_htf_defensive_harvest")
                    return actions

        # Stagnant Trade Fast Scalp Harvest (Salvage TP)
        # Scalper ethos: Never let a profitable trade rot into a loss when momentum stalls.
        if s.stagnant_harvest_enabled and state.opened_at is not None:
            current_profit = float(pos.profit or 0.0)
            should_harvest = False
            harvest_reason = ""
            # Don't cut trades if HTF is supporting our direction — let trend develop
            if (
                held >= s.stagnant_harvest_seconds
                and current_profit >= s.stagnant_min_profit_usd
                and htf_bias["verdict"] != "HTF_SUPPORTING"
            ):
                should_harvest = True
                harvest_reason = f"stagnant profit (held {int(held)}s, pnl=+${current_profit:.2f} >= ${s.stagnant_min_profit_usd:.2f})"
            elif (
                held >= s.stagnant_time_decay_seconds
                and current_profit >= 0.50
                and htf_bias["verdict"] != "HTF_SUPPORTING"
            ):
                should_harvest = True
                harvest_reason = f"time-decay salvage (held {int(held)}s, pnl=+${current_profit:.2f} >= $0.50)"

            if should_harvest:
                log.info(
                    "STAGNANT TRADE HARVEST: Closing ticket %s (%s %.2f @ %.2f -> %.2f, profit=+$%.2f, reason: %s)",
                    pos.ticket,
                    pos.side,
                    pos.volume,
                    pos.price_open,
                    price,
                    current_profit,
                    harvest_reason,
                )
                await self.client.close_position(pos.ticket, price=price)
                self.untrack(pos.ticket)
                actions.append("stagnant_harvest")
                return actions

        if state.r_distance <= 0:
            return actions

        profit = self._profit_distance(pos, price)

        # Partial take-profit.
        if (
            not state.partial_taken
            and s.partial_tp_at_r > 0
            and profit >= s.partial_tp_at_r * state.r_distance
        ):
            close_volume = round(pos.volume * (s.partial_tp_pct / 100.0), 2)
            if 0 < close_volume < pos.volume:
                await self.client.close_position(pos.ticket, price=price, volume=close_volume)
                state.partial_taken = True
                actions.append("partial_tp")

        # Early & Standard Break-even (moves SL to entry + 0.10 once profit >= 0.5R or standard BE at 1R).
        be_threshold = min(s.breakeven_at_r * state.r_distance, max(0.80, 0.5 * state.r_distance))
        if profit >= be_threshold:
            be_sl = round(state.entry + 0.10 if pos.is_long else state.entry - 0.10, 2)
            if pos.is_long and (pos.sl is None or pos.sl < be_sl):
                await self.client.modify_position(pos.ticket, sl=be_sl, tp=pos.tp)
                actions.append("breakeven")
            elif not pos.is_long and (pos.sl is None or pos.sl > be_sl):
                await self.client.modify_position(pos.ticket, sl=be_sl, tp=pos.tp)
                actions.append("breakeven")

        # Trailing stop.
        if s.trailing_enabled and profit >= s.breakeven_at_r * state.r_distance:
            trail = state.r_distance
            if atr and atr > 0:
                trail = max(state.r_distance, s.trailing_atr_mult * atr)
            if pos.is_long:
                new_sl = round(price - trail, 2)
                if new_sl > (pos.sl or -1e18):
                    await self.client.modify_position(pos.ticket, sl=new_sl, tp=pos.tp)
                    actions.append("trailing")
            else:
                new_sl = round(price + trail, 2)
                if new_sl < (pos.sl or 1e18):
                    await self.client.modify_position(pos.ticket, sl=new_sl, tp=pos.tp)
                    actions.append("trailing")

        return actions

    def compute_basket(self, positions: list[Position]) -> dict[str, Any]:
        """Compute aggregate metrics for multi-entry / rescue baskets."""
        if not positions:
            return {
                "count": 0,
                "total_volume": 0.0,
                "avg_entry": 0.0,
                "total_profit": 0.0,
                "side": None,
                "target_tp": None,
            }

        total_vol = sum(float(p.volume) for p in positions)
        if total_vol <= 0:
            return {"count": len(positions), "total_volume": 0.0, "avg_entry": 0.0, "total_profit": 0.0, "side": None, "target_tp": None}

        weighted_price = sum(float(p.price_open) * float(p.volume) for p in positions)
        avg_entry = round(weighted_price / total_vol, 2)
        total_profit = sum(float(p.profit) for p in positions)

        longs = [p for p in positions if p.is_long]
        shorts = [p for p in positions if not p.is_long]
        dominant_side = "BUY" if len(longs) >= len(shorts) else "SELL"

        # 1 pip on Gold (XAUUSD) = $0.10 in price distance
        buffer_usd = (self.settings.basket_tp_buffer_pips or 8.0) * 0.10
        if dominant_side == "BUY":
            target_tp = round(avg_entry + buffer_usd, 2)
        else:
            target_tp = round(avg_entry - buffer_usd, 2)

        return {
            "count": len(positions),
            "total_volume": round(total_vol, 2),
            "avg_entry": avg_entry,
            "total_profit": round(total_profit, 2),
            "side": dominant_side,
            "target_tp": target_tp,
        }

    async def manage_basket(
        self,
        positions: list[Position],
        current_bid: float | None = None,
        current_ask: float | None = None,
    ) -> list[str]:
        """Check and execute Basket Break-Even / Recovery Take-Profit.

        When multiple positions are open (rescue layering / pyramiding), closes
        the entire basket simultaneously once aggregate profit reaches the
        break-even buffer.
        """
        if len(positions) < 2:
            return []

        basket = self.compute_basket(positions)
        target_tp = basket["target_tp"]
        dominant_side = basket["side"]
        total_profit = basket["total_profit"]

        longs = [p for p in positions if p.is_long]
        shorts = [p for p in positions if not p.is_long]
        is_hedged_basket = len(longs) > 0 and len(shorts) > 0

        cur_price = current_bid if dominant_side == "BUY" else current_ask
        reached_target = False
        is_pyramid = False
        min_pyramid_basket_profit = max(7.50, round(basket["total_volume"] * 200.0, 2))
        min_basket_profit = max(3.50, basket["total_volume"] * 7.0 + 2.50)

        if is_hedged_basket:
            # Hedged cross-basket (both BUY and SELL active):
            # Target is strictly NET profit recovery (cannot use single price target)
            min_hedge_profit = max(1.50, basket["total_volume"] * 3.0 + 1.00)
            if total_profit >= min_hedge_profit:
                reached_target = True
            # Fast salvage: if hedged basket held >= 120s and net profit >= $0.50, unlock immediately
            now_dt = utcnow()
            max_held = max(
                (now_dt - (p.time or now_dt)).total_seconds() for p in positions
            )
            if max_held >= 120 and total_profit >= 0.50:
                reached_target = True
        else:
            # Check if this basket is a PYRAMID basket (averaging UP into running profit)
            # or a RESCUE basket (averaging DOWN to salvage a drawdown trade)
            has_pyramid_comment = any(
                "PYRAMID" in str(getattr(p, "comment", "") or "").upper() for p in positions
            )
            sorted_by_time = sorted(positions, key=lambda p: p.time or utcnow())
            oldest_pos = sorted_by_time[0]
            newest_pos = sorted_by_time[-1]
            price_ascending = (
                (dominant_side == "BUY" and newest_pos.price_open > oldest_pos.price_open + 0.30)
                or (dominant_side == "SELL" and newest_pos.price_open < oldest_pos.price_open - 0.30)
            )
            is_pyramid = has_pyramid_comment or price_ascending

            if is_pyramid:
                # PYRAMID BASKET: Scale-in on winning trend
                # Never trigger immediate break-even cut (avg_entry + buffer is behind current price!)
                # Let individual position SL/TP runner work, or close entire basket only when
                # cumulative runner target is achieved (total_profit >= $7.50).
                if total_profit >= min_pyramid_basket_profit:
                    reached_target = True
            else:
                # RESCUE BASKET: Averaging down to recover drawdown
                if target_tp is not None and cur_price is not None and cur_price > 0:
                    if dominant_side == "BUY" and cur_price >= target_tp:
                        reached_target = True
                    elif dominant_side == "SELL" and cur_price <= target_tp:
                        reached_target = True

                # Fallback trigger: net basket profit covers commission and min buffer ($4+ net)
                if not reached_target and total_profit >= min_basket_profit:
                    reached_target = True

                # Rescue Basket Solid Runner TP: if aggregate profit reaches solid runner target ($6.00+)
                solid_basket_tp = max(6.0, round(basket["total_volume"] * 75.0, 2))
                if total_profit >= solid_basket_tp:
                    reached_target = True

                # Rescue Basket Fast Salvage: if held >= 90s and aggregate profit >= $0.80, unlock immediately
                now_dt = utcnow()
                max_held = max(
                    (now_dt - (p.time or now_dt)).total_seconds() for p in positions
                )
                if max_held >= 90 and total_profit >= 0.80:
                    reached_target = True

                # Collective Stagnation Loss Cut: if rescue basket held >= 240s with persistent net loss
                # cut all positions collectively (never stranded individually)
                stagnation_ceiling = max(20.0, round(basket["total_volume"] * 1.50 * 100.0, 2))
                if max_held >= 240 and total_profit <= -stagnation_ceiling:
                    triggered = True
                    log.warning(
                        "BASKET STAGNATION CUT: Closing all %d %s positions collectively (held %ds, net_loss=%.2f <= -$%.2f)",
                        len(positions), dominant_side, int(max_held), total_profit, stagnation_ceiling,
                    )

        triggered = False
        # Basket Catastrophic Loss Guard (Collective Cutloss):
        # If adverse move continues relentlessly and total basket net loss exceeds risk ceiling,
        # cut ALL positions collectively. Never cut one and abandon the other!
        if not is_pyramid and not is_hedged_basket:
            max_basket_loss_usd = max(38.0, round(basket["total_volume"] * 2.50 * 100.0, 2))
            if total_profit <= -max_basket_loss_usd:
                triggered = True
                log.warning(
                    "BASKET CATASTROPHIC CUT: Closing all %d %s positions collectively (vol=%.2f, net_loss=%.2f <= -$%.2f)",
                    len(positions),
                    dominant_side,
                    basket["total_volume"],
                    total_profit,
                    max_basket_loss_usd,
                )

        if reached_target and not triggered:
            if not self.settings.basket_trailing_enabled:
                triggered = True
            else:
                # Cylinder 2: Dynamic Micro-Trailing Basket
                # Track peak profit reached while in harvest zone
                prev_peak = self._basket_peak_profit.get(dominant_side, total_profit)
                peak = max(prev_peak, total_profit)
                self._basket_peak_profit[dominant_side] = peak

                # Trail buffer: trail step $0.30 per 0.10 lot ($3.00/lot), minimum $1.20
                trail_buffer = max(1.20, (self.settings.basket_trail_step_usd or 0.30) * basket["total_volume"] * 10.0)
                base_min = min_pyramid_basket_profit if is_pyramid else min_basket_profit
                trail_floor = max(base_min * 0.70, peak - trail_buffer)

                # Trigger close if profit retraces below trail_floor or hits turbo ceiling ($20+)
                if total_profit <= trail_floor or total_profit >= 20.0:
                    triggered = True
                    self._basket_peak_profit.pop(dominant_side, None)
                else:
                    log.debug(
                        "BASKET TRAILING: %s cur=+$%.2f peak=+$%.2f floor=+$%.2f",
                        dominant_side,
                        total_profit,
                        peak,
                        trail_floor,
                    )

        actions: list[str] = []
        if triggered:
            is_cut = (not reached_target) and total_profit <= 0
            action_tag = "basket_cut_closed" if is_cut else "basket_tp_closed"
            log_title = "BASKET COLLECTIVE CUT EXECUTED" if is_cut else "BASKET RECOVERY TP TRIGGERED"
            log.info(
                "%s: closing %d positions (vol=%.2f, profit=+$%.2f, avg_entry=%.2f)",
                log_title,
                len(positions),
                basket["total_volume"],
                total_profit,
                basket["avg_entry"],
            )
            for pos in positions:
                try:
                    await self.client.close_position(pos.ticket)
                    self.untrack(pos.ticket)
                except Exception as exc:  # noqa: BLE001
                    log.warning("basket close failed for ticket %s: %s", pos.ticket, exc)
            actions.append(action_tag)

        return actions

    async def manage_all(
        self,
        prices: dict[int, float] | None = None,
        *,
        symbol: str | None = None,
        now: datetime | None = None,
    ) -> dict[int, list[str]]:
        """Manage every open position for the symbol."""
        positions = await self.client.positions(symbol or self.settings.mt5_symbol)
        results: dict[int, list[str]] = {}
        for pos in positions:
            price = (prices or {}).get(pos.ticket, pos.price_current)
            if price <= 0:
                continue
            try:
                results[pos.ticket] = await self.manage(pos, price, now=now)
            except Exception as exc:  # noqa: BLE001
                log.warning("manage ticket %s failed: %s", pos.ticket, exc)
        return results
