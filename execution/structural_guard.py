"""Multi-Timeframe Structural Guard & Fibonacci Dynamic SL Engine.

Translates professional top-down price action and Fibonacci analysis (M1 through H4)
into an automated structural invalidation engine ("SATPAM").

Key Principles:
  1. FIBONACCI 78.6% & GOLDEN POCKET DEFENSE:
     SL is anchored behind the deep Fibonacci retracement (78.6% Last Bastion)
     or structural swing origin, not choked by artificial micro-dollar caps or
     fragile local wicks.
  2. MINIMUM BREATHING RUNWAY:
     Gives trades at least 15-25 pips of runway to absorb normal market pullback
     into the Golden Pocket (50%-61.8%).
  3. ANTI-WICK PANIC (CANDLE FORMATION SHIELD):
     Spike wicks within the first 45 seconds that merely probe Line X by a few pips
     are treated as liquidity tests / sweeps, holding for candle close/rejection
     rather than panic-cutting at second 15.
  4. CLEAN STRUCTURAL CUT:
     When price genuinely breaks past Line X (or confirms after the formation window),
     the position is cut cleanly and objectively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config.logging import get_logger
from core.market_data import Bars

log = get_logger("execution.structural_guard")

__all__ = ["StructuralLevel", "StructuralEvaluation", "StructuralGuard"]


@dataclass(slots=True)
class StructuralLevel:
    price: float
    timeframe: str
    kind: str  # "SWING_LOW", "SWING_HIGH", "FIB_618", "FIB_786", "FIB_500", "STRUCTURAL_ORIGIN"
    description: str
    strength: float = 1.0


@dataclass(slots=True)
class StructuralEvaluation:
    side: str
    entry_price: float
    current_price: float
    level_x: float
    primary_level: StructuralLevel
    all_levels: list[StructuralLevel] = field(default_factory=list)
    is_breached: bool = False
    is_hard_breached: bool = False
    distance_pips: float = 0.0
    recommendation: str = "HOLD"  # "HOLD" or "CUT_LOSS"
    reasoning: str = ""


class StructuralGuard:
    """Multi-Timeframe Structural Guard & Fibonacci Confluence Engine."""

    def __init__(self, buffer_pips: float = 8.0) -> None:
        # Buffer in pips (1 pip = $0.10 on XAUUSD, so 8 pips = $0.80)
        self.buffer_pips = buffer_pips

    def _extract_swings(self, bars: Bars, timeframe: str) -> tuple[list[float], list[float]]:
        """Extract swing highs and swing lows using fractal pivots."""
        swing_highs: list[float] = []
        swing_lows: list[float] = []
        n = bars.n
        if n < 5:
            return swing_highs, swing_lows

        highs = bars.highs
        lows = bars.lows

        for i in range(2, n - 2):
            if highs[i] >= highs[i - 1] and highs[i] >= highs[i - 2] and highs[i] >= highs[i + 1] and highs[i] >= highs[i + 2]:
                swing_highs.append(round(highs[i], 2))
            if lows[i] <= lows[i - 1] and lows[i] <= lows[i - 2] and lows[i] <= lows[i + 1] and lows[i] <= lows[i + 2]:
                swing_lows.append(round(lows[i], 2))

        if not swing_highs and n >= 5:
            swing_highs.append(round(max(highs[-20:]), 2))
        if not swing_lows and n >= 5:
            swing_lows.append(round(min(lows[-20:]), 2))

        return swing_highs, swing_lows

    def _calculate_fibonacci(self, bars: Bars, timeframe: str) -> list[StructuralLevel]:
        """Calculate Fibonacci retracement levels from the dominant swing."""
        levels: list[StructuralLevel] = []
        n = bars.n
        if n < 10:
            return levels

        window = min(50, n)
        recent_highs = bars.highs[-window:]
        recent_lows = bars.lows[-window:]

        highest = max(recent_highs)
        lowest = min(recent_lows)
        rng = highest - lowest

        if rng < 1.5:  # Less than $1.50 move on gold is too small for meaningful Fib
            return levels

        high_idx = recent_highs.index(highest)
        low_idx = recent_lows.index(lowest)

        is_uptrend_swing = low_idx <= high_idx

        if is_uptrend_swing:
            fib_500 = highest - (rng * 0.500)
            fib_618 = highest - (rng * 0.618)
            fib_786 = highest - (rng * 0.786)

            levels.extend([
                StructuralLevel(round(fib_500, 2), timeframe, "FIB_500", f"{timeframe} Fib 50.0% ({fib_500:.2f})", 1.2),
                StructuralLevel(round(fib_618, 2), timeframe, "FIB_618", f"{timeframe} Fib 61.8% Golden Pocket ({fib_618:.2f})", 1.8),
                StructuralLevel(round(fib_786, 2), timeframe, "FIB_786", f"{timeframe} Fib 78.6% Last Bastion ({fib_786:.2f})", 2.5),
                StructuralLevel(round(lowest, 2), timeframe, "STRUCTURAL_ORIGIN", f"{timeframe} Swing Low Origin ({lowest:.2f})", 2.8),
            ])
        else:
            fib_500 = lowest + (rng * 0.500)
            fib_618 = lowest + (rng * 0.618)
            fib_786 = lowest + (rng * 0.786)

            levels.extend([
                StructuralLevel(round(fib_500, 2), timeframe, "FIB_500", f"{timeframe} Fib 50.0% ({fib_500:.2f})", 1.2),
                StructuralLevel(round(fib_618, 2), timeframe, "FIB_618", f"{timeframe} Fib 61.8% Golden Pocket ({fib_618:.2f})", 1.8),
                StructuralLevel(round(fib_786, 2), timeframe, "FIB_786", f"{timeframe} Fib 78.6% Last Bastion ({fib_786:.2f})", 2.5),
                StructuralLevel(round(highest, 2), timeframe, "STRUCTURAL_ORIGIN", f"{timeframe} Swing High Origin ({highest:.2f})", 2.8),
            ])

        return levels

    def evaluate_invalidation(
        self,
        *,
        side: str,
        entry_price: float,
        current_price: float,
        volume: float,
        state: Any,
        held_seconds: float = 0.0,
        max_risk_usd: float = 12.0,
    ) -> StructuralEvaluation:
        """
        Evaluate structural S&R, Fibonacci 78.6% Last Bastion, and compute Line X.
        Includes anti-wick protection for new trades (<45s).
        """
        side_upper = side.upper()
        is_buy = side_upper == "BUY"
        buffer_val = self.buffer_pips * 0.10  # e.g. 8 pips = $0.80 on gold

        vol_effective = max(0.01, volume)
        # Structural boundary budget: allows 25-40 pips breathing runway to reach real Fib 78.6%
        max_dist = max(2.50, round(max_risk_usd / (vol_effective * 100.0), 2))
        hard_boundary = round(entry_price - max_dist if is_buy else entry_price + max_dist, 2)

        collected_levels: list[StructuralLevel] = []

        # 1. Multi-timeframe scan (M5 -> M15 -> H1 -> H4)
        for tf, tf_weight in [("M5", 1.0), ("M15", 1.5), ("H1", 2.0), ("H4", 2.2)]:
            bars = Bars.for_timeframe(state, tf)
            if bars.n >= 5:
                swing_highs, swing_lows = self._extract_swings(bars, tf)
                if is_buy:
                    for low in swing_lows:
                        collected_levels.append(
                            StructuralLevel(
                                price=low,
                                timeframe=tf,
                                kind="SWING_LOW",
                                description=f"{tf} Swing Low Support ({low:.2f})",
                                strength=tf_weight,
                            )
                        )
                else:
                    for high in swing_highs:
                        collected_levels.append(
                            StructuralLevel(
                                price=high,
                                timeframe=tf,
                                kind="SWING_HIGH",
                                description=f"{tf} Swing High Resistance ({high:.2f})",
                                strength=tf_weight,
                            )
                        )

            # Fibonacci on M15 & H1
            if tf in ("M15", "H1"):
                fib_levels = self._calculate_fibonacci(bars, tf)
                collected_levels.extend(fib_levels)

        # 2. Select the true structural bastion (Prioritize Fib 78.6% & Structural Origin)
        # Ensure the level gives at least 12-15 pips breathing room from entry so it is NOT choked
        min_room_price = 1.20  # 12 pips

        if is_buy:
            valid_supports = [
                lvl for lvl in collected_levels
                if lvl.price <= (entry_price - min_room_price) and lvl.price >= (hard_boundary - 0.50)
            ]

            # If no support with 12 pips room, accept any support below entry
            if not valid_supports:
                valid_supports = [
                    lvl for lvl in collected_levels
                    if lvl.price < entry_price and lvl.price >= (hard_boundary - 0.50)
                ]

            if valid_supports:
                # Prioritize Fib 78.6% or Structural Origin, otherwise highest strength & deepest support
                fib_bastions = [lvl for lvl in valid_supports if lvl.kind in ("FIB_786", "STRUCTURAL_ORIGIN")]
                if fib_bastions:
                    best_support = min(fib_bastions, key=lambda lvl: lvl.price)
                else:
                    strongest = max(lvl.strength for lvl in valid_supports)
                    strong_pool = [lvl for lvl in valid_supports if lvl.strength >= strongest - 0.2]
                    best_support = min(strong_pool, key=lambda lvl: lvl.price)

                raw_level_x = round(best_support.price - buffer_val, 2)
                final_level_x = max(hard_boundary, raw_level_x)
                primary_level = best_support
            else:
                final_level_x = hard_boundary
                primary_level = StructuralLevel(
                    price=hard_boundary,
                    timeframe="RISK",
                    kind="RISK_CAP",
                    description=f"Structural Risk Boundary (-${max_risk_usd:.2f})",
                    strength=1.0,
                )

            is_breached = current_price <= final_level_x
            distance_pips = round((current_price - final_level_x) * 10.0, 1)
            overshoot_pips = round((final_level_x - current_price) * 10.0, 1)

        else:
            valid_resistances = [
                lvl for lvl in collected_levels
                if lvl.price >= (entry_price + min_room_price) and lvl.price <= (hard_boundary + 0.50)
            ]

            if not valid_resistances:
                valid_resistances = [
                    lvl for lvl in collected_levels
                    if lvl.price > entry_price and lvl.price <= (hard_boundary + 0.50)
                ]

            if valid_resistances:
                fib_bastions = [lvl for lvl in valid_resistances if lvl.kind in ("FIB_786", "STRUCTURAL_ORIGIN")]
                if fib_bastions:
                    best_resistance = max(fib_bastions, key=lambda lvl: lvl.price)
                else:
                    strongest = max(lvl.strength for lvl in valid_resistances)
                    strong_pool = [lvl for lvl in valid_resistances if lvl.strength >= strongest - 0.2]
                    best_resistance = max(strong_pool, key=lambda lvl: lvl.price)

                raw_level_x = round(best_resistance.price + buffer_val, 2)
                final_level_x = min(hard_boundary, raw_level_x)
                primary_level = best_resistance
            else:
                final_level_x = hard_boundary
                primary_level = StructuralLevel(
                    price=hard_boundary,
                    timeframe="RISK",
                    kind="RISK_CAP",
                    description=f"Structural Risk Boundary (-${max_risk_usd:.2f})",
                    strength=1.0,
                )

            is_breached = current_price >= final_level_x
            distance_pips = round((final_level_x - current_price) * 10.0, 1)
            overshoot_pips = round((current_price - final_level_x) * 10.0, 1)

        # 3. Candle Confirmation & Anti-Wick Protection for Line X SL
        # Prevent being stopped out by temporary intraday wicks / sweeps.
        # Cutloss is triggered if:
        # a) Catastrophic emergency breach (> 15.0 pips past Line X / severe slippage), OR
        # b) Confirmed M1 candle close beyond Line X (past initial 20s).
        # Otherwise, HOLD to allow candle formation / bounce.
        m1_bars = Bars.for_timeframe(state, "M1")
        m1_confirmed_close = False
        if m1_bars.n >= 2:
            last_closed_m1 = m1_bars.closes[-2]
            m1_confirmed_close = (last_closed_m1 <= final_level_x) if is_buy else (last_closed_m1 >= final_level_x)
            # If M1 frame is available, require confirmed M1 candle close (or catastrophic breach > 15 pips)
            is_hard_breached = is_breached and (overshoot_pips > 15.0 or (m1_confirmed_close and held_seconds >= 20.0))
        else:
            # Fallback when M1 frame is not supplied (test fixtures): require either overshoot > 10 pips or held >= 60s
            is_hard_breached = is_breached and (overshoot_pips > 10.0 or held_seconds >= 60.0)

        if is_hard_breached:
            rec = "CUT_LOSS"
            reason = (
                f"STRUCTURAL BREACH: Price ({current_price:.2f}) broken Line X ({final_level_x:.2f}) "
                f"anchored on {primary_level.description} (overshoot: {overshoot_pips:.1f}p, m1_closed={m1_confirmed_close}, held {int(held_seconds)}s). Invalidation confirmed."
            )
        elif is_breached and not is_hard_breached:
            rec = "HOLD"
            reason = (
                f"ANTI-WICK SHIELD: Price ({current_price:.2f}) temporarily probing Line X ({final_level_x:.2f}) "
                f"by {overshoot_pips:.1f}p. Holding for M1 candle close confirmation."
            )
        else:
            rec = "HOLD"
            reason = (
                f"HOLD TO BOUNCE: Price ({current_price:.2f}) fortified above/below Line X ({final_level_x:.2f}) "
                f"by {distance_pips:.1f} pips. Anchored on {primary_level.description}. Holding for recovery."
            )

        return StructuralEvaluation(
            side=side_upper,
            entry_price=round(entry_price, 2),
            current_price=round(current_price, 2),
            level_x=final_level_x,
            primary_level=primary_level,
            all_levels=collected_levels,
            is_breached=is_breached,
            is_hard_breached=is_hard_breached,
            distance_pips=distance_pips,
            recommendation=rec,
            reasoning=reason,
        )
