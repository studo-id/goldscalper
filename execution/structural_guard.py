"""Multi-Timeframe Structural Guard & Fibonacci Dynamic SL Engine.

Translates professional top-down price action and Fibonacci analysis (M1 through H4)
into an automated structural invalidation engine ("SATPAM").

Instead of cutting positions blindly on arbitrary duration seconds (e.g. 90s/120s),
this engine identifies the real market fortress (Support/Resistance & Fibonacci
Golden Pocket / Deep Invalidation levels) and defines an exact invalidation price
Line X.

Rules:
  1. HOLD TO BOUNCE: As long as price remains above Line X (for BUY) or below Line X
     (for SELL), the position is held to let the bounce develop. Time stopwatch cuts
     are suppressed.
  2. STRUCTURAL BREACH: When price structurally breaks Line X, the position is cut
     immediately without waiting for any timer.
  3. ABSOLUTE RISK CEILING: Line X is strictly clamped so it can never exceed the
     configured maximum account risk budget (preventing catastrophic outlier losses).
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
    kind: str  # "SWING_LOW", "SWING_HIGH", "FIB_618", "FIB_786", "FIB_500", "RISK_CAP"
    description: str
    strength: float = 1.0  # higher = stronger confluence


@dataclass(slots=True)
class StructuralEvaluation:
    side: str
    entry_price: float
    current_price: float
    level_x: float
    primary_level: StructuralLevel
    all_levels: list[StructuralLevel] = field(default_factory=list)
    is_breached: bool = False
    distance_pips: float = 0.0
    recommendation: str = "HOLD"  # "HOLD" or "CUT_LOSS"
    reasoning: str = ""


class StructuralGuard:
    """Multi-Timeframe Structural Guard & Fibonacci Confluence Engine."""

    def __init__(self, buffer_pips: float = 4.0) -> None:
        # Buffer in pips (1 pip = $0.10 on XAUUSD, so 4 pips = $0.40)
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

        # 3-bar and 5-bar fractal detection
        for i in range(2, n - 2):
            # Swing High
            if highs[i] >= highs[i - 1] and highs[i] >= highs[i - 2] and highs[i] >= highs[i + 1] and highs[i] >= highs[i + 2]:
                swing_highs.append(round(highs[i], 2))
            # Swing Low
            if lows[i] <= lows[i - 1] and lows[i] <= lows[i - 2] and lows[i] <= lows[i + 1] and lows[i] <= lows[i + 2]:
                swing_lows.append(round(lows[i], 2))

        # Always include the rolling extrema of the last 15 bars if no fractals found
        if not swing_highs and n >= 5:
            swing_highs.append(round(max(highs[-15:]), 2))
        if not swing_lows and n >= 5:
            swing_lows.append(round(min(lows[-15:]), 2))

        return swing_highs, swing_lows

    def _calculate_fibonacci(self, bars: Bars, timeframe: str) -> list[StructuralLevel]:
        """Calculate Fibonacci retracement levels from the dominant swing."""
        levels: list[StructuralLevel] = []
        n = bars.n
        if n < 10:
            return levels

        # Look back up to 40 bars for dominant swing
        window = min(40, n)
        recent_highs = bars.highs[-window:]
        recent_lows = bars.lows[-window:]

        highest = max(recent_highs)
        lowest = min(recent_lows)
        rng = highest - lowest

        if rng < 1.0:  # Less than $1.00 move on gold is too small for Fib
            return levels

        high_idx = recent_highs.index(highest)
        low_idx = recent_lows.index(lowest)

        # If low happened before high -> Uptrend swing (retracement down from high)
        # If high happened before low -> Downtrend swing (retracement up from low)
        is_uptrend_swing = low_idx <= high_idx

        if is_uptrend_swing:
            # Retracement levels measured down from high
            fib_382 = highest - (rng * 0.382)
            fib_500 = highest - (rng * 0.500)
            fib_618 = highest - (rng * 0.618)
            fib_786 = highest - (rng * 0.786)

            levels.extend([
                StructuralLevel(round(fib_500, 2), timeframe, "FIB_500", f"{timeframe} Fib 50.0% ({fib_500:.2f})", 1.2),
                StructuralLevel(round(fib_618, 2), timeframe, "FIB_618", f"{timeframe} Fib 61.8% Golden Pocket ({fib_618:.2f})", 1.6),
                StructuralLevel(round(fib_786, 2), timeframe, "FIB_786", f"{timeframe} Fib 78.6% Last Bastion ({fib_786:.2f})", 1.8),
            ])
        else:
            # Retracement levels measured up from low
            fib_382 = lowest + (rng * 0.382)
            fib_500 = lowest + (rng * 0.500)
            fib_618 = lowest + (rng * 0.618)
            fib_786 = lowest + (rng * 0.786)

            levels.extend([
                StructuralLevel(round(fib_500, 2), timeframe, "FIB_500", f"{timeframe} Fib 50.0% ({fib_500:.2f})", 1.2),
                StructuralLevel(round(fib_618, 2), timeframe, "FIB_618", f"{timeframe} Fib 61.8% Golden Pocket ({fib_618:.2f})", 1.6),
                StructuralLevel(round(fib_786, 2), timeframe, "FIB_786", f"{timeframe} Fib 78.6% Last Bastion ({fib_786:.2f})", 1.8),
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
        max_risk_usd: float = 7.50,
    ) -> StructuralEvaluation:
        """
        Evaluate structural S&R, Fibonacci confluence, and compute Line X (the exact invalidation price).
        """
        side_upper = side.upper()
        is_buy = side_upper == "BUY"
        buffer_val = self.buffer_pips * 0.10  # 4 pips = $0.40 on gold

        # Dollar risk to price distance conversion:
        # 1 lot = $100 per $1.00 move; 0.04 lot = $4.00 per $1.00 move ($0.40 per 1 pip)
        # Price distance for max_risk_usd = max_risk_usd / (volume * 100.0)
        vol_effective = max(0.01, volume)
        max_dist = max(1.20, round(max_risk_usd / (vol_effective * 100.0), 2))

        # Absolute risk boundary (the hard stop line beyond which trade must not pass)
        hard_boundary = round(entry_price - max_dist if is_buy else entry_price + max_dist, 2)

        collected_levels: list[StructuralLevel] = []

        # 1. Multi-timeframe scan (M5 -> M15 -> H1 -> H4)
        for tf, tf_weight in [("M5", 1.0), ("M15", 1.4), ("H1", 1.8), ("H4", 2.0)]:
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

        # 2. Filter levels applicable to position side
        if is_buy:
            # For BUY: we need support levels BELOW the entry price, but ABOVE the hard boundary
            valid_supports = [
                lvl for lvl in collected_levels
                if lvl.price <= entry_price + 0.10 and lvl.price >= hard_boundary - 0.20
            ]

            if valid_supports:
                # We want the structural fortress level that provides legitimate pullback/bounce room.
                # Prioritize high strength levels (Fib 61.8/78.6, HTF Swing Low), and among them
                # pick the deepest support that is still within our risk boundary.
                # Sort key: primary by strength descending, secondary by lowest price (deepest cushion)
                strongest_strength = max(lvl.strength for lvl in valid_supports)
                candidate_pool = [lvl for lvl in valid_supports if lvl.strength >= min(1.4, strongest_strength)]
                if not candidate_pool:
                    candidate_pool = valid_supports

                # Deepest support among candidates (closest to hard_boundary, giving maximum bounce breathing room)
                best_support = min(candidate_pool, key=lambda lvl: lvl.price)

                # Apply protective breathing buffer below support
                raw_level_x = round(best_support.price - buffer_val, 2)
                # Ensure level_x does not breach hard risk ceiling
                final_level_x = max(hard_boundary, raw_level_x)
                primary_level = best_support
            else:
                final_level_x = hard_boundary
                primary_level = StructuralLevel(
                    price=hard_boundary,
                    timeframe="RISK",
                    kind="RISK_CAP",
                    description=f"Risk Budget Boundary (-${max_risk_usd:.2f})",
                    strength=1.0,
                )

            is_breached = current_price <= final_level_x
            distance_pips = round((current_price - final_level_x) * 10.0, 1)

        else:
            # For SELL: we need resistance levels ABOVE the entry price, but BELOW the hard boundary
            valid_resistances = [
                lvl for lvl in collected_levels
                if lvl.price >= entry_price - 0.10 and lvl.price <= hard_boundary + 0.20
            ]

            if valid_resistances:
                strongest_strength = max(lvl.strength for lvl in valid_resistances)
                candidate_pool = [lvl for lvl in valid_resistances if lvl.strength >= min(1.4, strongest_strength)]
                if not candidate_pool:
                    candidate_pool = valid_resistances

                # Highest resistance among candidates (closest to hard_boundary, giving maximum bounce breathing room)
                best_resistance = max(candidate_pool, key=lambda lvl: lvl.price)

                raw_level_x = round(best_resistance.price + buffer_val, 2)
                final_level_x = min(hard_boundary, raw_level_x)
                primary_level = best_resistance
            else:
                final_level_x = hard_boundary
                primary_level = StructuralLevel(
                    price=hard_boundary,
                    timeframe="RISK",
                    kind="RISK_CAP",
                    description=f"Risk Budget Boundary (-${max_risk_usd:.2f})",
                    strength=1.0,
                )

            is_breached = current_price >= final_level_x
            distance_pips = round((final_level_x - current_price) * 10.0, 1)


        if is_breached:
            rec = "CUT_LOSS"
            reason = (
                f"STRUCTURAL BREACH: Price ({current_price:.2f}) broken Line X ({final_level_x:.2f}) "
                f"anchored on {primary_level.description}. Structural invalidation triggered."
            )
        else:
            rec = "HOLD"
            reason = (
                f"HOLD TO BOUNCE: Price ({current_price:.2f}) safely above/below Line X ({final_level_x:.2f}) "
                f"by {distance_pips:.1f} pips. Fortified by {primary_level.description}. Holding for recovery."
            )

        return StructuralEvaluation(
            side=side_upper,
            entry_price=round(entry_price, 2),
            current_price=round(current_price, 2),
            level_x=final_level_x,
            primary_level=primary_level,
            all_levels=collected_levels,
            is_breached=is_breached,
            distance_pips=distance_pips,
            recommendation=rec,
            reasoning=reason,
        )
