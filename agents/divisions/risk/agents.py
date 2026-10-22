"""Risk division agents — capital protection & scalper economics.

All six agents are **vote-neutral**; they surface parameters and guards through
``AgentSignal.metadata``. The pre-trade :mod:`execution.risk_gate` consumes them
and stamps ``size`` / ``sl`` / ``tp`` onto the final decision.

    4.1 PositionSizer    — vol-adjusted fractional, SPK-weighted later
    4.2 StopLoss         — ATR + structure, time stop
    4.3 TakeProfit       — R:R with partial fast-harvest
    4.4 EntryTiming      — market vs limit, spread guard
    4.5 DrawdownGuard    — daily/weekly DD circuit breaker
    4.6 CostMonitor      — spread/commission/slippage tracking
"""

from __future__ import annotations

from typing import Any

from agents.base import AgentSignal
from agents.divisions.risk.base import RiskAgent, estimate_atr
from agents.state import SharedState
from config.settings import Settings
from config.settings import settings as default_settings
from core.market_data import Bars


def round_to_step(value: float, step: float) -> float:
    """Round ``value`` to the nearest ``step`` (e.g. broker lot step)."""
    if step <= 0:
        return value
    return round(round(value / step) * step, 4)


def proposed_stop_distance(state: SharedState, settings: Settings) -> dict[str, Any]:
    """Shared SL proposal used by both the sizer and the stop/TP agents."""
    atr_val, tf = estimate_atr(state, period=14)
    atr_distance = atr_val * settings.atr_sl_multiplier
    bars = Bars.for_timeframe(state, tf) if tf else Bars()
    structure_distance = 0.0
    if bars.n >= 5:
        lookback = min(20, bars.n)
        swing = max(bars.highs[-lookback:]) - min(bars.lows[-lookback:])
        structure_distance = min(atr_distance * 1.5, swing * 0.25)
    distance = max(atr_distance, structure_distance)
    # Dynamic spread floor: stop loss must have breathing room beyond broker spread
    spread_points = float(state.spread_points or 0.0)
    spread_usd = (spread_points * 0.10) if spread_points > 0 else 0.80
    min_scalp_sl = max(2.50, round(spread_usd * 2.5, 2))
    distance = max(distance, min_scalp_sl)
    return {
        "distance": round(distance, 2),
        "atr_distance": round(atr_distance, 2),
        "structure_distance": round(structure_distance, 2),
        "atr": round(atr_val, 2),
        "atr_tf": tf,
    }


class PositionSizer(RiskAgent):
    """Vol-adjusted fractional sizing from equity, risk %, and stop distance."""

    id = "Risk-PositionSizer"

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or default_settings

    async def evaluate(self, state: SharedState) -> AgentSignal:
        s = self.settings
        equity = float(state.equity) if state.equity is not None else 10000.0
        stop = proposed_stop_distance(state, s)
        sl_distance = float(stop["distance"])
        if sl_distance <= 0:
            sl_distance = 1.5
        risk_amount = equity * (s.risk_per_trade_pct / 100.0)
        value_per_lot = sl_distance * s.contract_size

        if equity <= 0 or value_per_lot <= 0:
            return self.emit(
                "cannot size (no equity or no ATR)",
                {
                    "size": 0.0 if equity <= 0 else s.min_lot,
                    "equity": round(equity, 2),
                    "risk_amount": round(risk_amount, 2),
                    "sl_distance": sl_distance,
                    "atr": stop["atr"],
                    "atr_tf": stop["atr_tf"],
                },
            )

        raw = risk_amount / value_per_lot
        size = min(s.max_lot, max(s.min_lot, round_to_step(raw, s.lot_step)))

        # === THE JUGGLER: Dynamic Portfolio-Aware Target-Seeking Lot Sizing ===
        # As daily PnL approaches daily target, dynamically scale down lot size.
        if s.juggler_enabled and s.lot_sizing_mode == "TARGET_SEEKING" and state.balance_start_of_day is not None:
            balance_sod = float(state.balance_start_of_day or equity)
            target_usd = balance_sod * (s.daily_profit_target_pct / 100.0)
            realized_pnl = float(state.daily_realized_pnl or 0.0)
            remaining_usd = max(0.0, target_usd - realized_pnl)

            if remaining_usd <= 0:
                return self.emit(
                    "target already reached, sizing zero",
                    {
                        "size": 0.0,
                        "sizing_mode": "TARGET_SEEKING",
                        "target_usd": round(target_usd, 2),
                        "realized_pnl": round(realized_pnl, 2),
                        "remaining_usd": 0.0,
                    },
                )

            # 1. Dynamic Base Clamp scales with Account Balance & Live Average Win
            equity_risk_budget = equity * (s.risk_per_trade_pct / 100.0)
            equity_clamp_baseline = round(equity_risk_budget * 1.25, 2)
            base_clamp = max(s.hard_loss_clamp_usd if s.hard_loss_clamp_enabled else 7.0, equity_clamp_baseline)
            live_avg_win = float(state.extra.get("live_avg_win", 0.0) or 0.0)
            if live_avg_win >= 2.0:
                base_clamp = max(base_clamp, round(live_avg_win * 1.1, 2))

            # 2. Portfolio Health Multiplier (AGENTS.md Juggler Directive):
            daily_pnl_pct = float(state.daily_pnl_pct or 0.0)
            extra = state.extra if hasattr(state, "extra") and isinstance(state.extra, dict) else {}
            spk_conf = float(extra.get("spk_confidence", 0.0) or 0.0)
            spk_score = float(extra.get("spk_score", 0.0) or 0.0)
            is_high_conviction = (
                bool(extra.get("high_confluence"))
                or spk_conf >= 0.70
                or abs(spk_score) >= 5.0
            )
            setup_grade = "A+" if is_high_conviction else ("A" if abs(spk_score) >= 3.0 or spk_conf >= 0.55 else "B")

            # Target pursuit demand factor: when chasing daily sprint target, quantify the pull
            target_urgency = min(1.35, max(1.0, round(remaining_usd / max(1.0, target_usd * 0.5), 3)))

            max_scalper_lot = float(getattr(s, "max_scalper_lot", 0.08) or 0.08)

            if daily_pnl_pct < 0:
                # DEFENSE: baseline shrinks strictly to protect equity (AGENTS.md: 0.02 - 0.04 lot ceiling)
                mode_name = "DEFENSE"
                # If in deep drawdown (<= -4.0%), lot strictly capped at 0.02 - 0.03 lot
                defense_ceiling = 0.03 if daily_pnl_pct <= -4.0 else 0.04
                max_scalper_lot = min(max_scalper_lot, defense_ceiling)
                health_mult = max(0.40, min(0.75, round(1.0 + (daily_pnl_pct / 20.0), 3)))
                if is_high_conviction:
                    # Grade A+ High-Conviction in DEFENSE allows controlled recovery up to defense ceiling
                    health_mult = min(1.00, round(health_mult * 1.35, 3))
            elif daily_pnl_pct >= 3.0:
                # GROWTH: expand lot dynamically using house money from broker gains
                mode_name = "GROWTH"
                health_mult = min(2.50, round(1.0 + ((daily_pnl_pct - 3.0) / 10.0), 3))
                if is_high_conviction:
                    health_mult = min(2.50, round(health_mult * target_urgency, 3))
            else:
                # BALANCED: standard operating baseline
                mode_name = "BALANCED"
                if is_high_conviction:
                    conv_boost = 1.40 if getattr(s, "aggressive_scalper", False) else 1.20
                    health_mult = round(conv_boost * target_urgency, 3)
                elif setup_grade == "A":
                    conv_boost = 1.15 if getattr(s, "aggressive_scalper", False) else 1.05
                    health_mult = round(conv_boost * target_urgency, 3)
                else:
                    health_mult = 1.00

            dynamic_clamp_budget = round(base_clamp * health_mult, 2)

            # 3. Dynamic Balance-Scaled Base Lot:
            # Derived from actual equity, risk per trade %, and stop loss distance
            base_lot = raw * health_mult

            # 4. Daily Sprint Target Proximity Smooth Tapering:
            # As remaining target approaches 0, smoothly taper lot to ensure risk-free landing
            proximity_ratio = remaining_usd / target_usd if target_usd > 0 else 1.0
            if proximity_ratio <= 0.10:
                # Inside the final 10% sprint: taper lot smoothly in proportion to remaining target
                taper_factor = max(0.25, min(1.0, proximity_ratio / 0.10))
            else:
                taper_factor = 1.0

            dynamic_size = min(max_scalper_lot, base_lot * taper_factor)
            size = min(max_scalper_lot, min(s.max_lot, max(s.min_lot, round_to_step(dynamic_size, s.lot_step))))

            return self.emit(
                f"TARGET_SEEKING [{mode_name} Grade {setup_grade} x{health_mult:.2f}]: rem=${remaining_usd:.2f}, clamp=${dynamic_clamp_budget:.2f}, lot={size}",
                {
                    "size": size,
                    "sizing_mode": "TARGET_SEEKING",
                    "portfolio_mode": mode_name,
                    "setup_grade": setup_grade,
                    "high_conviction": is_high_conviction,
                    "health_multiplier": health_mult,
                    "dynamic_clamp_budget": dynamic_clamp_budget,
                    "target_usd": round(target_usd, 2),
                    "realized_pnl": round(realized_pnl, 2),
                    "remaining_usd": round(remaining_usd, 2),
                    "equity": round(equity, 2),
                    "risk_amount": round(risk_amount, 2),
                    "sl_distance": sl_distance,
                    "atr": stop["atr"],
                    "atr_tf": stop["atr_tf"],
                },
            )

        return self.emit(
            f"risk {s.risk_per_trade_pct}% of {equity:.2f} @ SL {sl_distance}",
            {
                "size": size,
                "raw_size": round(raw, 4),
                "equity": round(equity, 2),
                "risk_amount": round(risk_amount, 2),
                "value_per_lot": round(value_per_lot, 2),
                "sl_distance": sl_distance,
                "atr": stop["atr"],
                "atr_tf": stop["atr_tf"],
            },
        )


class StopLoss(RiskAgent):
    """Stop distance from ATR + recent structure, plus a time stop."""

    id = "Risk-StopLoss"

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or default_settings

    async def evaluate(self, state: SharedState) -> AgentSignal:
        s = self.settings
        stop = proposed_stop_distance(state, s)
        return self.emit(
            f"stop {stop['distance']} (atr {stop['atr_distance']} / "
            f"struct {stop['structure_distance']})",
            {
                "sl_distance": stop["distance"],
                "atr_distance": stop["atr_distance"],
                "structure_distance": stop["structure_distance"],
                "atr": stop["atr"],
                "atr_tf": stop["atr_tf"],
                "time_stop_s": s.max_hold_seconds,
                "method": "atr+structure",
            },
        )


class TakeProfit(RiskAgent):
    """Dynamic R:R take-profit linked to portfolio health, live avg win, and sprint target."""

    id = "Risk-TakeProfit"

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or default_settings

    async def evaluate(self, state: SharedState) -> AgentSignal:
        s = self.settings
        stop = proposed_stop_distance(state, s)
        sl_distance = float(stop["distance"])

        daily_pnl_pct = float(getattr(state, "daily_pnl_pct", 0.0) or 0.0)
        rem_target = (
            state.extra.get("remaining_target_usd")
            if hasattr(state, "extra") and isinstance(state.extra, dict)
            else None
        )
        live_avg_win = (
            float(state.extra.get("live_avg_win", 0.0) or 0.0)
            if hasattr(state, "extra") and isinstance(state.extra, dict)
            else 0.0
        )

        # Dynamic R:R & TP distance based on portfolio state:
        if rem_target is not None and 0 < rem_target <= 20.0:
            # Finish line proximity: calibrate target to capture the remaining sprint goal
            tp_distance = max(2.50, min(round(rem_target, 2), round(sl_distance * 2.0, 2)))
            rr = round(tp_distance / sl_distance, 2) if sl_distance > 0 else s.default_rr
            mode_desc = f"Finish Line Proximity (rem=${rem_target:.2f})"
        elif daily_pnl_pct < 0:
            extra = state.extra if hasattr(state, "extra") and isinstance(state.extra, dict) else {}
            is_high_conviction = (
                bool(extra.get("high_confluence"))
                or float(extra.get("spk_confidence", 0.0) or 0.0) >= 0.70
                or float(extra.get("spk_score", 0.0) or 0.0) >= 5.0
            )
            if is_high_conviction:
                rr = 1.80
                tp_distance = round(max(7.50, sl_distance * rr), 2)
                mode_desc = f"DEFENSE HIGH-CONVICTION RUNNER (pnl={daily_pnl_pct:.1f}%)"
            else:
                # Defense mode: tighter RR for rapid profit banking
                rr = 1.30
                tp_distance = round(max(3.00, sl_distance * rr), 2)
                mode_desc = f"DEFENSE (pnl={daily_pnl_pct:.1f}%)"
        elif daily_pnl_pct >= 3.0:
            # Growth mode: runner expansion with house money
            rr = 2.0
            base_runner = max(sl_distance * rr, round(live_avg_win * 1.3, 2))
            tp_distance = round(max(6.00, base_runner), 2)
            mode_desc = f"GROWTH (pnl=+{daily_pnl_pct:.1f}%)"
        else:
            # Balanced mode: default RR anchored to live avg win
            rr = s.default_rr
            base_tp = (
                max(sl_distance * rr, round(live_avg_win * 1.1, 2))
                if live_avg_win >= 2.0
                else sl_distance * rr
            )
            tp_distance = round(base_tp, 2)
            mode_desc = "BALANCED"

        partials = [
            {"r": round(rr * 0.5, 2), "pct": 50},
            {"r": rr, "pct": 50},
        ]
        return self.emit(
            f"TP at {rr}R (dist {tp_distance}) [{mode_desc}]",
            {
                "rr": rr,
                "tp_distance": tp_distance,
                "sl_distance": sl_distance,
                "partials": partials,
                "method": "dynamic_portfolio_tp",
                "portfolio_mode": mode_desc,
            },
        )


class EntryTiming(RiskAgent):
    """Choose market vs limit, flag unfavourable spread, and monitor trade stalls."""

    id = "Risk-EntryTiming"

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or default_settings

    async def evaluate(self, state: SharedState) -> AgentSignal:
        s = self.settings
        spread = state.spread_points
        max_spread = s.max_spread_points
        spread_ok = spread is None or spread <= max_spread
        market_ok = spread is not None and spread <= max_spread * 0.5
        atr_val, _ = estimate_atr(state)

        # Active trade stall diagnostics:
        stalled_positions: list[dict[str, Any]] = []
        has_stalled_profit = False
        has_stalled_drawdown = False

        for pos in state.positions:
            age = int(pos.get("age_seconds", 0) or 0)
            pnl = float(pos.get("profit", 0.0) or 0.0)
            ticket = pos.get("ticket")
            direction = pos.get("direction")
            if age >= 90:  # held >= 90s in M1 scalper is considered stalling
                stalled_info = {
                    "ticket": ticket,
                    "direction": direction,
                    "age_s": age,
                    "profit": pnl,
                    "status": "STALLED_PROFIT" if pnl > 0 else "STALLED_DRAWDOWN",
                }
                stalled_positions.append(stalled_info)
                if pnl >= s.stagnant_min_profit_usd:
                    has_stalled_profit = True
                elif pnl < 0:
                    has_stalled_drawdown = True

        continuation_viable = (
            len(state.positions) < s.max_open_positions
            and (has_stalled_drawdown or (bool(stalled_positions) and spread_ok))
        )

        # BizDev Friction Guard: Monitor net friction ratio ((friction - rebates) / gross profit)
        friction_blocked = False
        friction_ratio_val = 0.0
        adaptive_tp_expansion = False
        net_friction = 0.0
        est_rebate = 0.0
        if s.bizdev_enabled:
            daily_gross = float(state.daily_gross_profit or 0.0)
            daily_friction = float(state.daily_friction_cost or 0.0)
            daily_lots = float(state.daily_lots_traded or 0.0)
            est_rebate = daily_lots * float(getattr(s, "rebate_per_lot_usd", 6.0))
            net_friction = max(0.0, daily_friction - est_rebate)

            # Daily portfolio health check (The Juggler Directive)
            daily_pnl_pct = float(getattr(state, "daily_pnl_pct", 0.0) or 0.0)

            if daily_gross >= 10.0 and net_friction > 0:
                friction_ratio_val = round((net_friction / daily_gross) * 100.0, 1)
                if friction_ratio_val > s.max_friction_ratio_pct:
                    # In DEFENSE mode (drawdown < 0%), friction kills the day to preserve capital
                    if daily_pnl_pct < 0.0:
                        friction_blocked = True
                    else:
                        # In BALANCED/GROWTH mode, we do NOT freeze the engine (avoid deadlock paradox)
                        # Instead, flag adaptive TP expansion so runner targets wide swings
                        adaptive_tp_expansion = True

        diagnostic_notes = [f"entry={('market' if market_ok else 'limit')}", f"spread_ok={spread_ok}"]
        if friction_blocked:
            diagnostic_notes.append(f"friction_blocked={friction_ratio_val}%>{s.max_friction_ratio_pct}%(DEFENSE)")
        elif adaptive_tp_expansion:
            diagnostic_notes.append(f"friction_tp_expanded={friction_ratio_val}%(GROWTH/BALANCED)")
        if stalled_positions:
            diagnostic_notes.append(f"stalled_trades={len(stalled_positions)}")
            if has_stalled_profit:
                diagnostic_notes.append("harvest_candidate=YES")
            if continuation_viable:
                diagnostic_notes.append("continuation_viable=YES")

        return self.emit(
            " | ".join(diagnostic_notes),
            {
                "order_type": "market" if market_ok else "limit",
                "spread_points": spread,
                "max_spread_points": max_spread,
                "spread_ok": spread_ok,
                "limit_offset": round(atr_val * 0.25, 2),
                "stalled_positions": stalled_positions,
                "has_stalled_profit": has_stalled_profit,
                "has_stalled_drawdown": has_stalled_drawdown,
                "continuation_viable": continuation_viable,
                "friction_blocked": friction_blocked,
                "friction_ratio": friction_ratio_val,
                "adaptive_tp_expansion": adaptive_tp_expansion,
                "net_friction": round(net_friction, 2),
                "est_rebate": round(est_rebate, 2),
            },
        )


class DrawdownGuard(RiskAgent):
    """Daily/weekly drawdown and losing-streak circuit breaker."""

    id = "Risk-DrawdownGuard"

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or default_settings

    async def evaluate(self, state: SharedState) -> AgentSignal:
        s = self.settings
        reasons: list[str] = []

        # === THE JUGGLER: Daily Profit Lock (Circuit Breaker) ===
        if s.juggler_enabled and s.daily_profit_lock_enabled:
            daily_pnl_pct = float(state.daily_pnl_pct or 0.0)
            if daily_pnl_pct >= s.daily_profit_target_pct:
                lock_reason = (
                    f"DAILY TARGET ACHIEVED: +{daily_pnl_pct:.1f}% >= "
                    f"+{s.daily_profit_target_pct:.1f}% — PROFIT LOCKED FOR THE DAY!"
                )
                return self.emit(
                    lock_reason,
                    {
                        "halt": True,
                        "veto": True,
                        "daily_profit_locked": True,
                        "daily_pnl_pct": round(daily_pnl_pct, 4),
                        "target_pct": s.daily_profit_target_pct,
                        "reason": lock_reason,
                    },
                )

        effective_max_loss = s.max_daily_loss_pct
        if state.daily_loss_exceeded or state.daily_pnl_pct <= -effective_max_loss:
            reasons.append(
                f"daily pnl {state.daily_pnl_pct:.2f}% <= -{effective_max_loss:.2f}%"
            )
        if state.weekly_loss_exceeded or state.weekly_pnl_pct <= -s.max_weekly_loss_pct:
            reasons.append(
                f"weekly pnl {state.weekly_pnl_pct:.2f}% <= -{s.max_weekly_loss_pct:.2f}%"
            )
        if state.consecutive_losses >= s.max_consecutive_losses:
            reasons.append(
                f"{state.consecutive_losses} consecutive losses >= {s.max_consecutive_losses}"
            )

        halt = bool(reasons)
        return self.emit(
            ("HALT: " + "; ".join(reasons)) if halt else "drawdown within limits",
            {
                "halt": halt,
                "reason": "; ".join(reasons) if reasons else None,
                "daily_pnl_pct": round(state.daily_pnl_pct, 4),
                "weekly_pnl_pct": round(state.weekly_pnl_pct, 4),
                "consecutive_losses": state.consecutive_losses,
            },
        )


class CostMonitor(RiskAgent):
    """Track spread, commission, and estimated slippage against limits."""

    id = "Risk-CostMonitor"

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or default_settings

    async def evaluate(self, state: SharedState) -> AgentSignal:
        s = self.settings
        spread = state.spread_points
        cost_ok = spread is None or spread <= s.max_spread_points
        slippage = round((spread or 0.0) * 0.5, 2)
        return self.emit(
            f"spread={spread} cost_ok={cost_ok} commission={s.commission_per_lot}/lot",
            {
                "spread_points": spread,
                "max_spread_points": s.max_spread_points,
                "commission_per_lot": s.commission_per_lot,
                "slippage_points_est": slippage,
                "cost_ok": cost_ok,
            },
        )


RISK_AGENT_CLASSES: tuple[type[RiskAgent], ...] = (
    PositionSizer,
    StopLoss,
    TakeProfit,
    EntryTiming,
    DrawdownGuard,
    CostMonitor,
)


__all__ = [
    "PositionSizer",
    "StopLoss",
    "TakeProfit",
    "EntryTiming",
    "DrawdownGuard",
    "CostMonitor",
    "RISK_AGENT_CLASSES",
    "round_to_step",
    "proposed_stop_distance",
]
