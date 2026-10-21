"""Order manager.

Turns an approved :class:`~spk.decision.SPKDecision` into a broker order,
records the trade, and fires notifications. The single boundary between the
decision brain and the MT5 client.

Deterministic; all broker calls are awaited through the injected client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from agents.state import SharedState, utcnow
from config.logging import get_logger
from config.settings import Settings
from config.settings import settings as default_settings
from core.mt5_connector import (
    SIDE_BUY,
    SIDE_SELL,
    MT5Client,
    OrderRequest,
)
from spk.decision import ACTION_BUY, ACTION_SELL, SPKDecision

log = get_logger("execution.order_manager")

__all__ = ["ExecutionResult", "OrderManager"]


@dataclass
class ExecutionResult:
    ok: bool
    ticket: int | None = None
    trade_id: str | None = None
    price: float | None = None
    size: float = 0.0
    reason: str | None = None


@dataclass
class OrderManager:
    """Submits orders for tradable decisions and records them."""

    client: MT5Client
    settings: Settings = field(default_factory=lambda: default_settings)
    trade_repo: Any | None = None
    notifier: Any | None = None
    _cooldown_until: datetime | None = None
    _cooldown_reason: str | None = None
    _cooldown_m1_bucket: int | None = None

    def arm_m1_candle_cooldown(self, min_seconds: int = 60, reason: str = "post_cutloss") -> None:
        """Arms cooldown to wait until the current M1 candle finishes and a NEW M1 candle begins,
        guaranteeing a minimum buffer (default min 60 seconds).
        """
        now = utcnow()
        current_epoch_min = int(now.timestamp()) // 60
        self._cooldown_m1_bucket = current_epoch_min

        # Seconds remaining until the boundary of the current M1 candle (:00)
        current_sec = now.second + (now.microsecond / 1_000_000.0)
        remaining_current_candle = 60.0 - current_sec

        # If remaining time in current candle is small (< 40s),
        # waiting only until next candle boundary would unblock too early into the shockwave.
        # Wait for the next M1 candle to finish as well.
        if remaining_current_candle < 40.0:
            target_seconds = remaining_current_candle + 60.0
        else:
            target_seconds = remaining_current_candle

        target_seconds = max(float(min_seconds), target_seconds)
        seconds_int = round(target_seconds)
        self._cooldown_until = now + timedelta(seconds=seconds_int)
        self._cooldown_reason = reason
        log.info(
            "M1 CANDLE COOLDOWN ARMED: blocking entries for %ds until new M1 candle (until %s, bucket=%d, reason: %s)",
            seconds_int,
            self._cooldown_until.strftime("%H:%M:%S"),
            self._cooldown_m1_bucket,
            reason,
        )

    def arm_cooldown(self, seconds: int = 60, reason: str = "post_trade") -> None:
        # Route cutloss/loss cooldowns automatically through M1-candle cooldown
        if any(w in reason.lower() for w in ("cut", "clamp", "loss")):
            return self.arm_m1_candle_cooldown(min_seconds=max(60, seconds), reason=reason)
        self._cooldown_until = utcnow() + timedelta(seconds=seconds)
        self._cooldown_reason = reason
        self._cooldown_m1_bucket = None
        log.info(
            "COOLDOWN ARMED: blocking new initial entries for %ds (until %s, reason: %s)",
            seconds,
            self._cooldown_until.strftime("%H:%M:%S"),
            reason,
        )

    @property
    def in_cooldown(self) -> bool:
        now = utcnow()
        if self._cooldown_until is not None:
            if now < self._cooldown_until:
                return True
            # Time expired, ensure M1 candle bucket requirement is also cleared
            if self._cooldown_m1_bucket is not None:
                current_epoch_min = int(now.timestamp()) // 60
                if current_epoch_min <= self._cooldown_m1_bucket:
                    return True
            self._cooldown_until = None
            self._cooldown_reason = None
            self._cooldown_m1_bucket = None
            return False

        if self._cooldown_m1_bucket is not None:
            current_epoch_min = int(now.timestamp()) // 60
            if current_epoch_min <= self._cooldown_m1_bucket:
                return True
            self._cooldown_m1_bucket = None

        return False

    async def open_positions(self, symbol: str | None = None) -> int:
        try:
            return len(await self.client.positions(symbol or self.settings.mt5_symbol))
        except Exception as exc:  # noqa: BLE001
            log.warning("positions query failed: %s", exc)
            return 0

    async def execute(
        self, decision: SPKDecision, state: SharedState | None = None
    ) -> ExecutionResult | None:
        """Submit the decision as an order. Returns ``None`` when skipped."""
        if not decision.tradable:
            return None
        if decision.size <= 0:
            return ExecutionResult(ok=False, reason="zero size")

        # === THE JUGGLER: Daily Profit Lock / Circuit Breaker Enforcement ===
        if state is not None and getattr(state, "daily_profit_locked", False):
            log.warning(
                "ORDER BLOCKED: Daily sprint target achieved (+%.1f%%) — system locked for the day.",
                float(getattr(state, "daily_pnl_pct", 0.0) or 0.0),
            )
            return ExecutionResult(ok=False, reason="daily_profit_locked")

        symbol = self.settings.mt5_symbol
        open_positions_list = []
        try:
            open_positions_list = await self.client.positions(symbol)
        except Exception as exc:  # noqa: BLE001
            log.warning("positions query failed: %s", exc)

        open_count = len(open_positions_list)
        if open_count == 0 and self.in_cooldown:
            rem = int((self._cooldown_until - utcnow()).total_seconds()) if self._cooldown_until else 0
            log.debug("Execution skipped: in cooldown (%ds remaining, reason: %s)", rem, self._cooldown_reason)
            return ExecutionResult(ok=False, reason=f"post-trade cooldown active ({rem}s remaining)")

        if open_count >= self.settings.max_open_positions:
            log.info("max open positions reached (%d)", open_count)
            return ExecutionResult(ok=False, reason="max open positions")

        side = SIDE_BUY if decision.action == ACTION_BUY else SIDE_SELL
        entry = decision.entry if decision.entry is not None else (
            state.last_price() if state is not None else None
        )
        if entry is None and state is not None:
            entry = state.bid if decision.action == ACTION_SELL else state.ask
        if entry is None and open_positions_list:
            p0 = open_positions_list[0]
            entry = float(p0.price_current or p0.price_open)

        exec_volume = float(decision.size)
        order_comment = f"SPK {decision.action} conf={decision.confidence:.2f}"

        # Dynamic Data-Driven Boundary Gate (Anti-Buying the Top & Anti-Selling the Bottom):
        # Dynamically evaluates M5 candle structure, cluster S/R, and confirmed breakout/breakdown.
        # Bypasses block ONLY IF data confirms valid breakout/breakdown or active trending regime.
        blocked_sr, sr_reason = self._check_dynamic_sr_boundary(decision.action, entry, state)
        if blocked_sr:
            log.warning("DYNAMIC DATA GATE: %s", sr_reason)
            return ExecutionResult(ok=False, reason=sr_reason)

        # Adverse Candle Momentum Guard (Anti-Falling Knife & Anti-Rocket Surge):
        # Applies to BOTH Initial Entry (open_count == 0) and Layered entries.
        blocked_momentum, mom_reason = self._check_adverse_candle_momentum(decision.action, state)
        if blocked_momentum:
            log.warning("MOMENTUM CANDLE GUARD: %s", mom_reason)
            return ExecutionResult(ok=False, reason=mom_reason)

        # Multi-Entry & Smart Rescue Recovery Evaluation
        if open_count > 0:
            if not self.settings.multi_entry_enabled:
                log.debug("multi_entry disabled; holding single open position")
                return ExecutionResult(ok=False, reason="single position mode (multi-entry disabled)")

            # --- THE JUGGLER: Portfolio-First & Daily Target Gate for Layering ---
            daily_pnl_pct = float(getattr(state, "daily_pnl_pct", 0.0) or 0.0) if state else 0.0
            rem_target = (
                state.extra.get("remaining_target_usd")
                if state and hasattr(state, "extra") and isinstance(state.extra, dict)
                else None
            )

            # 1. Finish Line Lockdown: Near daily sprint goal (remaining <= $20), strictly 1 position
            if rem_target is not None and 0 < rem_target <= 20.0:
                log.info(
                    "JUGGLER MULTI-ENTRY BLOCKED: Finish line proximity ($%.2f remaining <= $20) — single position mode",
                    rem_target,
                )
                return ExecutionResult(ok=False, reason="finish line proximity (multi-entry blocked)")

            # 2. Drawdown Defense Mode: In deep drawdown (<= -4.0%), strictly 1 position
            if daily_pnl_pct <= -4.0:
                log.info(
                    "JUGGLER MULTI-ENTRY BLOCKED: Defense mode drawdown (%.2f%% <= -4.0%%) — single position mode",
                    daily_pnl_pct,
                )
                return ExecutionResult(ok=False, reason="drawdown defense (multi-entry blocked)")

            same_side_positions = [
                p for p in open_positions_list
                if (p.is_long and decision.action == ACTION_BUY) or (not p.is_long and decision.action == ACTION_SELL)
            ]
            opposite_positions = [
                p for p in open_positions_list
                if (p.is_long and decision.action == ACTION_SELL) or (not p.is_long and decision.action == ACTION_BUY)
            ]

            # Independent Ping-Pong Scalper Logic:
            # Allows trading both sides when momentum flips, with min distance to prevent clustering
            if opposite_positions:
                min_pingpong_dist = 1.0  # 10 pips separation from nearest opposite entry
                if entry is not None:
                    closest_opp = min(abs(entry - float(p.price_open)) for p in opposite_positions)
                    if closest_opp < min_pingpong_dist:
                        return ExecutionResult(
                            ok=False,
                            reason=f"ping-pong entry too close to opposite trade ({closest_opp:.2f} < {min_pingpong_dist:.2f} USD)",
                        )

                # Anti-Hedging S/R Barrier: Block opposite hedge at Support Floor / Resistance Ceiling
                # during contested/sideways conditions unless clean breakout is confirmed.
                is_sr_blocked, sr_reason = self._check_opposite_sr_barrier(decision.action, entry, state)
                if is_sr_blocked:
                    log.warning("PING-PONG REJECTED AT S/R: %s", sr_reason)
                    return ExecutionResult(ok=False, reason=sr_reason)

                order_comment = f"PINGPONG {decision.action} conf={decision.confidence:.2f}"
                log.info(
                    "PING-PONG ENTRY APPROVED: %s @ %s against %d opposite trade(s)",
                    decision.action,
                    entry,
                    len(opposite_positions),
                )

            if same_side_positions:
                if len(same_side_positions) >= self.settings.rescue_max_layers:
                    log.info("rescue max layers reached (%d)", len(same_side_positions))
                    return ExecutionResult(ok=False, reason="rescue max layers reached")

                min_distance_usd = (self.settings.rescue_min_distance_pips or 15.0) * 0.10
                # Enforce dynamic Juggler spacing calibrated to lot size & Dynamic Clamp thresholds:
                if state is not None:
                    if daily_pnl_pct < 0:
                        # In DEFENSE mode: spacing 18 pips ($1.80) aligns with 0.04 lot clamp zone,
                        # allowing Layer 2 to step in before clamp cut while preventing clustering < 18 pips
                        min_distance_usd = 1.80
                    else:
                        # In NORMAL/GROWTH mode: spacing 15 pips ($1.50)
                        min_distance_usd = max(1.50, min_distance_usd)
                else:
                    # When state is None (unit tests), check stalled flag
                    any_stalled = any(
                        (utcnow() - (p.time or utcnow())).total_seconds() >= 90
                        for p in same_side_positions
                    )
                    if any_stalled:
                        min_distance_usd = min(min_distance_usd, 1.0)

                if entry is None:
                    log.warning("entry price unresolved; rejecting multi-entry layer to prevent duplicate clustering")
                    return ExecutionResult(ok=False, reason="entry price unresolved for multi-entry")

                closest_dist = min(abs(entry - float(p.price_open)) for p in same_side_positions)
                if closest_dist < min_distance_usd:
                    log.debug(
                        "entry distance too close to existing position (%.2f < %.2f USD)",
                        closest_dist,
                        min_distance_usd,
                    )
                    return ExecutionResult(
                        ok=False,
                        reason=f"distance too close ({closest_dist:.2f} < {min_distance_usd:.2f})",
                    )

                avg_existing = sum(float(p.price_open) for p in same_side_positions) / len(same_side_positions)
                is_rescue = (
                    (decision.action == ACTION_BUY and entry is not None and entry < avg_existing)
                    or (decision.action == ACTION_SELL and entry is not None and entry > avg_existing)
                )

                layer_num = len(same_side_positions) + 1
                if is_rescue:
                    if not self.settings.rescue_mode_enabled:
                        return ExecutionResult(ok=False, reason="rescue mode disabled")

                    # Anti-Waterfall / Anti-Rocket Guard & S/R Boundary Guard (GANAS CERDAS)
                    if state is not None:
                        if decision.action == ACTION_BUY and state.extra.get("session_waterfall_bear"):
                            log.warning("ANTI-WATERFALL GUARD: blocked BUY rescue during session waterfall drop")
                            return ExecutionResult(ok=False, reason="anti-waterfall guard: bearish session drop")
                        if decision.action == ACTION_SELL and state.extra.get("session_waterfall_bull"):
                            log.warning("ANTI-WATERFALL GUARD: blocked SELL rescue during session rocket spike")
                            return ExecutionResult(ok=False, reason="anti-waterfall guard: bullish session spike")
                        if decision.action == ACTION_BUY and state.extra.get("active_sr_barrier") == "RESISTANCE":
                            log.warning("S/R BARRIER GUARD: blocked BUY rescue layer falling away from resistance")
                            return ExecutionResult(ok=False, reason="sr barrier: blocked buy rescue at resistance breakdown")
                        if decision.action == ACTION_SELL and state.extra.get("active_sr_barrier") == "SUPPORT":
                            log.warning("S/R BARRIER GUARD: blocked SELL rescue layer bouncing away from support")
                            return ExecutionResult(ok=False, reason="sr barrier: blocked sell rescue at support bounce")

                        # Anti-Falling Knife / Rocket Spike Guard on Rescue Layers:
                        # Prevent averaging down into high-velocity adverse moves (waterfalls > 35 pips or flash bar > 20 pips)
                        m1_bars = state.frames.get("M1") if state.frames else None
                        if m1_bars and len(m1_bars) >= 3:
                            last_3 = m1_bars[-3:]
                            def _c_open(b: Any) -> float:
                                return float(getattr(b, "open", b.get("open", 0.0) if isinstance(b, dict) else 0.0))
                            def _c_close(b: Any) -> float:
                                return float(getattr(b, "close", b.get("close", 0.0) if isinstance(b, dict) else 0.0))

                            if decision.action == ACTION_BUY:
                                last_3_red = all(_c_close(b) < _c_open(b) for b in last_3)
                                adverse_span = _c_open(last_3[0]) - _c_close(last_3[-1])
                                has_flash_drop = any((_c_open(b) - _c_close(b)) >= 2.00 for b in last_3)
                                if last_3_red and (adverse_span >= 3.50 or has_flash_drop):
                                    log.warning(
                                        "FALLING KNIFE GUARD: blocked BUY rescue into high-velocity drop (span=%.2f USD, flash=%s)",
                                        adverse_span, has_flash_drop,
                                    )
                                    return ExecutionResult(ok=False, reason="falling knife guard: high-velocity drop")
                            elif decision.action == ACTION_SELL:
                                last_3_green = all(_c_close(b) > _c_open(b) for b in last_3)
                                adverse_span = _c_close(last_3[-1]) - _c_open(last_3[0])
                                has_flash_pump = any((_c_close(b) - _c_open(b)) >= 2.00 for b in last_3)
                                if last_3_green and (adverse_span >= 3.50 or has_flash_pump):
                                    log.warning(
                                        "ROCKET SPIKE GUARD: blocked SELL rescue into high-velocity surge (span=%.2f USD, flash=%s)",
                                        adverse_span, has_flash_pump,
                                    )
                                    return ExecutionResult(ok=False, reason="rocket spike guard: high-velocity surge")

                    # Smart Asymmetric Multiplier (default 1.0 = flat lot for GANAS CERDAS)
                    mult = (self.settings.rescue_multiplier or 1.0) ** (layer_num - 1)
                    raw_size = exec_volume * mult
                    step = self.settings.lot_step or 0.01
                    exec_volume = min(self.settings.max_lot, round(round(raw_size / step) * step, 2))
                    # In DEFENSE mode (drawdown < 0%), enforce strict risk conservation: cap Layer 2 to 0.02 lot
                    if state is not None and daily_pnl_pct < 0:
                        exec_volume = min(0.02, exec_volume)
                    order_comment = f"RESCUE L{layer_num} {decision.action} lot={exec_volume:.2f}"
                    log.info(
                        "RESCUE RECOVERY TRIGGERED: Layer %d %s @ %s (lot=%.2f, mult=%.2fx, dist=%.2f USD from avg)",
                        layer_num,
                        decision.action,
                        entry,
                        exec_volume,
                        mult,
                        abs(entry - avg_existing) if entry else 0.0,
                    )
                else:
                    # Pyramiding into same direction:
                    existing_profit = sum(float(p.profit or 0.0) for p in same_side_positions)
                    if existing_profit <= 0:
                        log.info(
                            "JUGGLER PYRAMID BLOCKED: Existing positions not in profit (floating pnl=$%.2f <= 0)",
                            existing_profit,
                        )
                        return ExecutionResult(ok=False, reason="pyramid requires positive existing profit")

                    # In DEFENSE mode (drawdown < 0%):
                    # Only allow Risk-Free Pyramiding if existing positions have locked profit >= $2.00 (20 pips)
                    if state is not None and daily_pnl_pct < 0:
                        min_defense_profit = 2.00
                        if existing_profit < min_defense_profit:
                            log.info(
                                "JUGGLER PYRAMID BLOCKED: Pyramiding during drawdown requires floating profit >= $%.2f (current=$%.2f)",
                                min_defense_profit,
                                existing_profit,
                            )
                            return ExecutionResult(ok=False, reason="drawdown pyramid requires locked profit >= $2.00")
                        # Cap layer 2 volume to 0.02 lot in defense mode
                        exec_volume = min(0.02, exec_volume)

                    order_comment = f"PYRAMID L{layer_num} {decision.action} conf={decision.confidence:.2f}"
                    log.info(
                        "PYRAMID SCALING TRIGGERED: Layer %d %s @ %s (lot=%.2f, floating_profit=$%.2f)",
                        layer_num,
                        decision.action,
                        entry,
                        exec_volume,
                        existing_profit,
                    )
                    # Cylinder 4: Risk-Free Pyramiding
                    # When scaling into winning trade, tighten existing position SL to lock in gain
                    if self.settings.risk_free_pyramiding and entry is not None:
                        for p in same_side_positions:
                            p_open = float(p.price_open)
                            locked_sl = round(p_open + 0.20 if p.is_long else p_open - 0.20, 2)
                            try:
                                if (p.is_long and (p.sl is None or p.sl < locked_sl)) or (
                                    not p.is_long and (p.sl is None or p.sl > locked_sl)
                                ):
                                    await self.client.modify_position(p.ticket, sl=locked_sl, tp=p.tp)
                                    log.info("PYRAMID RISK-FREE LOCK: Ticket %s SL secured at %.2f", p.ticket, locked_sl)
                            except Exception as exc:  # noqa: BLE001
                                log.debug("failed to lock pyramid SL for %s: %s", p.ticket, exc)

        request = OrderRequest(
            symbol=symbol,
            side=side,
            volume=float(exec_volume),
            price=None,  # market order
            sl=decision.sl,
            tp=decision.tp,
            magic=self.settings.mt5_magic,
            deviation=self.settings.mt5_deviation,
            comment=order_comment,
            order_type="market",
        )

        try:
            result = await self.client.order_send(request)
        except Exception as exc:  # noqa: BLE001 - broker failure must not kill loop
            log.error("order_send failed: %s", exc)
            await self._alert(f"order error: {exc}")
            return ExecutionResult(ok=False, reason=str(exc))

        if not result.ok:
            log.warning("order rejected: %s", result.comment)
            await self._alert(f"order rejected: {result.comment}")
            return ExecutionResult(ok=False, reason=result.comment or "rejected")

        fill_price = result.price if result.price is not None else entry
        trade_id = await self._record(decision, result.ticket, fill_price)
        await self._notify_opened(decision, fill_price, result.ticket)
        log.info(
            "opened %s %.2f @ %s ticket=%s trade=%s",
            decision.action,
            exec_volume,
            fill_price,
            result.ticket,
            trade_id,
        )
        return ExecutionResult(
            ok=True,
            ticket=result.ticket,
            trade_id=trade_id,
            price=fill_price,
            size=exec_volume,
        )

    async def _record(
        self, decision: SPKDecision, ticket: int | None, price: float | None
    ) -> str | None:
        if self.trade_repo is None:
            return None
        try:
            return await self.trade_repo.open_trade(
                {
                    "symbol": self.settings.mt5_symbol,
                    "direction": decision.action,
                    "size": decision.size,
                    "entry_price": price,
                    "sl": decision.sl,
                    "tp": decision.tp,
                    "spk_score": decision.score,
                    "spk_confidence": decision.confidence,
                    "mt5_ticket": ticket,
                    "metadata": {"division_scores": decision.division_scores},
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("trade record failed: %s", exc)
            return None

    async def _notify_opened(
        self, decision: SPKDecision, price: float | None, ticket: int | None
    ) -> None:
        if self.notifier is None:
            return
        try:
            await self.notifier.trade_opened(
                {
                    "symbol": self.settings.mt5_symbol,
                    "direction": decision.action,
                    "size": decision.size,
                    "entry_price": price,
                    "sl": decision.sl,
                    "tp": decision.tp,
                    "spk_confidence": decision.confidence,
                    "ticket": ticket,
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("notify failed: %s", exc)

    async def _alert(self, text: str) -> None:
        if self.notifier is None:
            return
        try:
            await self.notifier.alert(text)
        except Exception as exc:  # noqa: BLE001
            log.debug("alert failed: %s", exc)

    def _check_dynamic_sr_boundary(
        self, action: str, entry: float | None, state: SharedState | None
    ) -> tuple[bool, str]:
        """Verify whether an order is entering into an S/R boundary.

        Permits entry ONLY IF there is a confirmed higher-timeframe trend breakdown/breakout
        or active trending regime.
        Blocks SELL at support floor and BUY at resistance ceiling during
        contested / sideways / bounce conditions without confirmed breakout data.
        """
        if entry is None or state is None:
            return False, ""

        m5_bars = state.frames.get("M5")
        if not m5_bars or len(m5_bars) < 5:
            return False, ""

        def _val(b: Any, field_name: str) -> float:
            if isinstance(b, dict):
                return float(b.get(field_name, 0.0) or 0.0)
            return float(getattr(b, field_name, 0.0) or 0.0)

        lookback = min(20, len(m5_bars))
        recent_bars = m5_bars[-lookback:]
        prior_bars = recent_bars[:-1] if len(recent_bars) > 1 else recent_bars
        cluster_support = min(_val(b, "low") for b in prior_bars)
        cluster_resistance = max(_val(b, "high") for b in prior_bars)

        sr_sup = state.extra.get("sr_support")
        sr_res = state.extra.get("sr_resistance")
        if sr_sup and float(sr_sup) > cluster_support:
            cluster_support = float(sr_sup)
        if sr_res and float(sr_res) < cluster_resistance:
            cluster_resistance = float(sr_res)

        range_height = max(1.0, cluster_resistance - cluster_support)
        # Dynamic buffer: at least $1.50 (15 pips) up to 25% of the range (capped at $3.50 / 35 pips)
        sr_buffer = max(1.50, min(3.50, round(range_height * 0.25, 2)))
        market_regime = str(state.extra.get("market_regime", "") or "").upper()

        last_b = m5_bars[-1]
        prev_b = m5_bars[-2] if len(m5_bars) >= 2 else last_b
        prev2_b = m5_bars[-3] if len(m5_bars) >= 3 else prev_b

        is_lh_ll = (_val(last_b, "high") < _val(prev_b, "high") < _val(prev2_b, "high")) if len(m5_bars) >= 3 else False
        is_hh_hl = (_val(last_b, "low") > _val(prev_b, "low") > _val(prev2_b, "low")) if len(m5_bars) >= 3 else False
        struct_event = getattr(state, "extra", {}).get("struct_event") or ("LH_LL" if is_lh_ll else ("HH_HL" if is_hh_hl else "RANGE"))

        last_m5_close = _val(last_b, "close")

        if action == ACTION_SELL:
            # Entering within dynamic buffer of support floor or probing below it without confirmed M5 close
            if entry <= (cluster_support + sr_buffer):
                is_clean_breakdown = (
                    last_m5_close < (cluster_support - 0.50)
                    and struct_event in ("LH_LL", "BREAKDOWN")
                )
                if not is_clean_breakdown:
                    dist_to_support = entry - cluster_support
                    # If price is already AT or BELOW support (dist_to_support <= 0), probing unconfirmed territory -> STRICTLY BLOCK
                    if dist_to_support <= 0:
                        return (
                            True,
                            f"Blocked SELL probing below support floor (${cluster_support:.2f}, entry=${entry:.2f}) without confirmed M5 candle close",
                        )
                    return (
                        True,
                        f"Blocked SELL near support floor (${cluster_support:.2f}, dist={dist_to_support:.2f}, buffer={sr_buffer:.2f}) without confirmed M5 breakdown close",
                    )

        elif action == ACTION_BUY:
            # Entering within dynamic buffer of resistance ceiling or probing above it without confirmed M5 close
            if entry >= (cluster_resistance - sr_buffer):
                is_clean_breakout = (
                    last_m5_close > (cluster_resistance + 0.50)
                    and struct_event in ("HH_HL", "BREAKOUT")
                )
                if not is_clean_breakout:
                    dist_to_res = cluster_resistance - entry
                    # If price is already AT or ABOVE resistance (dist_to_res <= 0), probing unconfirmed territory -> STRICTLY BLOCK
                    if dist_to_res <= 0:
                        return (
                            True,
                            f"Blocked BUY probing above resistance ceiling (${cluster_resistance:.2f}, entry=${entry:.2f}) without confirmed M5 candle close",
                        )
                    return (
                        True,
                        f"Blocked BUY near resistance ceiling (${cluster_resistance:.2f}, dist={dist_to_res:.2f}, buffer={sr_buffer:.2f}) without confirmed M5 breakout close",
                    )

        return False, ""

    # Backward compatibility alias
    _check_opposite_sr_barrier = _check_dynamic_sr_boundary

    def _check_adverse_candle_momentum(
        self, action: str, state: SharedState | None
    ) -> tuple[bool, str]:
        """Anti-Falling Knife & Anti-Rocket Surge Guard.

        Prevents opening an initial or rescue order in the middle of a high-velocity
        candle slamming down or rocket spiking.
        """
        if state is None or not state.frames:
            return False, ""

        m1_bars = state.frames.get("M1")
        if not m1_bars or len(m1_bars) < 2:
            return False, ""

        def _val(b: Any, field_name: str) -> float:
            if isinstance(b, dict):
                return float(b.get(field_name, 0.0) or 0.0)
            return float(getattr(b, field_name, 0.0) or 0.0)

        cur_bar = m1_bars[-1]
        cur_open = _val(cur_bar, "open")
        cur_close = _val(cur_bar, "close")
        cur_high = _val(cur_bar, "high")
        cur_low = _val(cur_bar, "low")
        cur_span = max(0.01, cur_high - cur_low)

        lookback = min(3, len(m1_bars))
        recent_bars = m1_bars[-lookback:]

        if action == ACTION_BUY:
            # 1. Single-bar flash dump in active M1 candle: drop >= $1.80 (18 pips) and red
            cur_drop = cur_open - cur_close
            lower_wick = max(0.0, cur_close - cur_low) / cur_span if cur_span > 0 else 0.0

            # If current bar is actively dropping heavily and has no strong rejection wick (lower wick < 35%)
            if cur_drop >= 1.80 and lower_wick < 0.35:
                return (
                    True,
                    f"falling knife guard: active flash dump (current candle dropping -${cur_drop:.2f} USD / {cur_drop*10:.0f} pips)",
                )

            # 2. Multi-bar cascading waterfall: last 2-3 bars are all red with cumulative adverse drop >= $3.00 (30 pips)
            all_red = all(_val(b, "close") < _val(b, "open") for b in recent_bars)
            cascade_drop = _val(recent_bars[0], "open") - cur_close
            has_flash_drop = any((_val(b, "open") - _val(b, "close")) >= 1.80 for b in recent_bars)
            if all_red and (cascade_drop >= 3.00 or has_flash_drop) and cur_close < cur_open:
                return (
                    True,
                    f"falling knife guard: cascade drop -${cascade_drop:.2f} USD across {lookback} bars",
                )

        elif action == ACTION_SELL:
            # 1. Single-bar flash pump in active M1 candle: surge >= $1.80 (18 pips) and green
            cur_pump = cur_close - cur_open
            upper_wick = max(0.0, cur_high - cur_close) / cur_span if cur_span > 0 else 0.0

            # If current bar is actively surging heavily and has no strong rejection wick (upper wick < 35%)
            if cur_pump >= 1.80 and upper_wick < 0.35:
                return (
                    True,
                    f"rocket surge guard: active rocket pump (current candle surging +${cur_pump:.2f} USD / {cur_pump*10:.0f} pips)",
                )

            # 2. Multi-bar cascading rocket: last 2-3 bars are all green with cumulative adverse surge >= $3.00 (30 pips)
            all_green = all(_val(b, "close") > _val(b, "open") for b in recent_bars)
            cascade_pump = cur_close - _val(recent_bars[0], "open")
            has_flash_pump = any((_val(b, "close") - _val(b, "open")) >= 1.80 for b in recent_bars)
            if all_green and (cascade_pump >= 3.00 or has_flash_pump) and cur_close > cur_open:
                return (
                    True,
                    f"rocket surge guard: cascade pump +${cascade_pump:.2f} USD across {lookback} bars",
                )

        return False, ""
