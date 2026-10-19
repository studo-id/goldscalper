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


def evaluate_htf_reversal_bias(pos_direction: str, context: dict[str, Any] | None) -> dict[str, Any]:
    """
    Evaluate Higher Timeframe (HTF) agents with rich historical candle data:
      - TF-H4-Structure: H4 trend and market structure
      - TF-H1-Regime: H1 21-EMA slope and box regime
      - TF-M30-Momentum: M30 momentum & exhaustion wicks
      - TF-M15-Liquidity: M15 liquidity sweeps & order blocks
      - Struct-MarketStructure: M5 Break of Structure (BOS) / Change of Character (CHoCH)

    Returns alignment score and verdict:
      - HTF_SUPPORTING: Higher timeframe trend is with our trade (permission to hold for reversal).
      - HTF_OPPOSING: Higher timeframe structure has broken against trade (early cutloss, do not hope).
      - NEUTRAL: Conflicted / sideways.
    """
    if not context:
        return {"score": 0.0, "verdict": "NEUTRAL", "supporting": [], "opposing": []}

    decision = context.get("decision")
    if not decision or not getattr(decision, "votes", None):
        return {"score": 0.0, "verdict": "NEUTRAL", "supporting": [], "opposing": []}

    htf_weights = {
        "TF-H4-Structure": 2.5,
        "TF-H1-Regime": 2.5,
        "TF-M30-Momentum": 1.5,
        "TF-M15-Liquidity": 1.5,
        "Struct-MarketStructure": 1.0,
    }

    dir_upper = pos_direction.upper()
    pos_vote = 1 if dir_upper == "BUY" else -1

    weighted_alignment = 0.0
    total_weight = 0.0
    supporting = []
    opposing = []

    for signal in decision.votes:
        agent_id = getattr(signal, "agent_id", "")
        if agent_id in htf_weights:
            w = htf_weights[agent_id]
            vote = getattr(signal, "vote", 0)
            conf = float(getattr(signal, "confidence", 0.5) or 0.5)
            total_weight += w

            # Does this HTF scout agree with our open position?
            if (vote > 0 and pos_vote > 0) or (vote < 0 and pos_vote < 0):
                weighted_alignment += w * conf
                supporting.append(f"{agent_id}(conf={conf:.2f})")
            elif (vote > 0 and pos_vote < 0) or (vote < 0 and pos_vote > 0):
                weighted_alignment -= w * conf
                opposing.append(f"{agent_id}(conf={conf:.2f})")

    norm_score = round(weighted_alignment / max(1.0, total_weight), 2)
    verdict = "NEUTRAL"
    if norm_score >= 0.25:
        verdict = "HTF_SUPPORTING"
    elif norm_score <= -0.25:
        verdict = "HTF_OPPOSING"

    return {
        "score": norm_score,
        "verdict": verdict,
        "supporting": supporting,
        "opposing": opposing,
    }


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
        htf_bias = evaluate_htf_reversal_bias(pos.side, ctx)

        held = (moment - state.opened_at).total_seconds() if state.opened_at is not None else 0.0

        # Hard time-stop.
        if state.opened_at is not None and held >= s.max_hold_seconds:
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

        # --- THE JUGGLER: Dynamic Anti-Bleeding & In-Flight Reversal Matrix ---
        if s.juggler_enabled:
            current_loss = float(pos.profit or 0.0)
            live_avg_win = float(ctx.get("live_avg_win", 0.0) or 0.0)

            # 1. Physical Noise Floor: Minimum 16 pips ($1.60) breathing room on Gold
            min_breath_usd = round(pos.volume * 1.60 * 100.0, 2)
            equity = float(ctx.get("equity", 0.0) or 0.0) if ctx else 0.0
            equity_clamp = round(equity * (s.risk_per_trade_pct / 100.0) * 1.25, 2) if equity > 0 else s.hard_loss_clamp_usd
            base_clamp = max(s.hard_loss_clamp_usd, equity_clamp)
            if live_avg_win >= 2.0:
                base_clamp = max(base_clamp, round(live_avg_win * 1.1, 2))
            effective_clamp_usd = max(min_breath_usd, base_clamp)

            # 2. Phase 0: Noise Absorption Grace Period (0 - 15s)
            # Never allow 2-second spread noise to cut trade unless catastrophic gap (>1.6x clamp)
            if held < 15 and current_loss > -(effective_clamp_usd * 1.6):
                pass  # Grace period: absorb spread friction

            # 3. Phase 1: HTF Trend Breakdown (Early Cut — Do NOT Hope!)
            # If floating loss >= 65% of clamp AND Higher Timeframes (H4/H1/M30/M15) are actively opposing us:
            elif (
                held >= 15
                and current_loss <= -(effective_clamp_usd * 0.65)
                and htf_bias["verdict"] == "HTF_OPPOSING"
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

            # 4. Phase 2: Dynamic Hard Clamp (Adaptive & HTF-Protected)
            elif s.hard_loss_clamp_enabled and current_loss <= -abs(effective_clamp_usd):
                # If HTF strongly supports position and held < 60s, allow small 1.25x buffer for reversal wick
                if htf_bias["verdict"] == "HTF_SUPPORTING" and held < 60 and current_loss > -(effective_clamp_usd * 1.25):
                    log.info(
                        "JUGGLER HTF REVERSAL BUFFER: Holding ticket %s (held %ds, loss=%.2f) — HTF trend is supporting: %s",
                        pos.ticket,
                        int(held),
                        current_loss,
                        htf_bias["supporting"],
                    )
                else:
                    log.warning(
                        "JUGGLER DYNAMIC CLAMP: Cutting ticket %s (%s %.2f, loss=%.2f <= -$%.2f [HTF=%s, avg_win $%.2f])",
                        pos.ticket,
                        pos.side,
                        pos.volume,
                        current_loss,
                        effective_clamp_usd,
                        htf_bias["verdict"],
                        live_avg_win,
                    )
                    await self.client.close_position(pos.ticket, price=price)
                    self.untrack(pos.ticket)
                    actions.append("juggler_dynamic_clamp")
                    return actions

            # 5. Phase 3: Duration Stagnation Cut (90s - 150s with no reversal momentum)
            elif state.opened_at is not None and held >= 90:
                duration_loss_limit = max(2.50, round(effective_clamp_usd * 0.60, 2))
                if current_loss <= -duration_loss_limit and htf_bias["verdict"] != "HTF_SUPPORTING":
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

            # 6. Phase 4: Time-Decay Loss Cut (>180s)
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

            # 5. Dynamic Risk-Free Break-Even Lock:
            # As soon as profit reaches >= $2.50 (or ~25 pips), slide SL to entry + 0.15 (locks in +$0.60 profit risk-free)
            be_sl = round(state.entry + 0.15 if pos.is_long else state.entry - 0.15, 2)
            be_trigger_usd = max(2.50, round(pos.volume * 0.50 * 100.0, 2))
            if current_profit >= be_trigger_usd:
                if pos.is_long and (pos.sl is None or pos.sl < be_sl):
                    await self.client.modify_position(pos.ticket, sl=be_sl, tp=pos.tp)
                    pos.sl = be_sl
                    actions.append("breakeven_locked")
                elif not pos.is_long and (pos.sl is None or pos.sl > be_sl):
                    await self.client.modify_position(pos.ticket, sl=be_sl, tp=pos.tp)
                    pos.sl = be_sl
                    actions.append("breakeven_locked")

            # 6. Momentum-Decay Profit Harvest:
            # Let winning trades breathe! Only harvest if HTF opposes or target >= $7.50 / 1.25x avg win
            live_avg_win = float(ctx.get("live_avg_win", 0.0) or 0.0)
            runner_target = max(7.50, round(live_avg_win * 1.25, 2)) if live_avg_win >= 2.0 else 7.50
            if s.juggler_enabled and held >= 90:
                # If HTF scouts actively oppose us, take profit defensively before momentum fully reverses
                if htf_bias["verdict"] == "HTF_OPPOSING" and current_profit >= 3.50:
                    log.info(
                        "JUGGLER HTF DEFENSIVE HARVEST: Ticket %s held %ds, profit=+$%.2f with HTF opposing: %s",
                        pos.ticket,
                        int(held),
                        current_profit,
                        htf_bias["opposing"],
                    )
                    await self.client.close_position(pos.ticket, price=price)
                    self.untrack(pos.ticket)
                    actions.append("juggler_htf_defensive_harvest")
                    return actions

                # If runner target reached, harvest solid win!
                elif current_profit >= runner_target:
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

        triggered = False
        if reached_target:
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
            log.info(
                "BASKET RECOVERY TP TRIGGERED: closing %d positions (vol=%.2f, profit=+$%.2f, avg_entry=%.2f)",
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
            actions.append("basket_tp_closed")

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
