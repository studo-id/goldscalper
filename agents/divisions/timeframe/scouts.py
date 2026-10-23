"""The 7-Scouts Boardroom — timeframe-division agents.

Reimplemented on the GoldScalper agent contract from the read-only reference
``AcengGold/core/multi_tf_consensus.py`` (never imported, never edited). Each
scout emits an :class:`~agents.base.AgentSignal` carrying a vote, a confidence
(= the original "strength") and, where mandated, a hard veto
(``VETO_BUY`` / ``VETO_SELL``).

Scouts, fast -> slow:
    M1 Sniper · M5 Inspector · M15 Liquidity · M30 Momentum
    H1 Regime · H4 Structure · D1 Macro
"""

from __future__ import annotations

from typing import Any

from agents.base import AgentSignal
from agents.divisions.timeframe.base import TimeframeAgent
from agents.state import (
    VETO_BUY,
    VETO_SELL,
    VOTE_BUY,
    VOTE_NEUTRAL,
    VOTE_SELL,
    SharedState,
)
from config.settings import settings as default_settings
from core.indicators import atr, ema_last, mean, wick_stats

# Tunables (mirror the reference thresholds).
SNIPER_REJECTION = 0.40
SNIPER_THIN_BODY = 0.35
M5_DISPLACEMENT_ATR = 1.2
M30_EXHAUSTION_WICK = 0.50
M30_THIN_BODY = 0.35
D1_EXTREME_FRACTION = 0.10
H4_BLOCK_FRACTION = 0.05
H1_BOX_FRACTION = 0.15
H1_CHOP_SWITCHES = 4
H1_TREND_SWITCHES = 2
H1_FLAT_RANGE = 8.0  # XAUUSD dollars; very tight H1 box


def _pct(value: float) -> float:
    return round(value * 100.0, 1)


def _direction_from_ema(
    close: float, ema_fast: float, ema_slow: float, slope: float
) -> tuple[int, str]:
    """Shared bullish/bearish/neutral read from EMA alignment + slope."""
    # Bullish: price above fast EMA AND (fast >= slow or positive slope)
    if close >= ema_fast and (ema_fast >= ema_slow or slope > 0) and slope >= 0:
        return VOTE_BUY, "BULLISH"
    if close >= ema_fast >= ema_slow:
        return VOTE_BUY, "BULLISH"
    # Bearish: price below fast EMA AND (fast <= slow or negative slope)
    if close <= ema_fast and (ema_fast <= ema_slow or slope < 0) and slope <= 0:
        return VOTE_SELL, "BEARISH"
    if close <= ema_fast <= ema_slow:
        return VOTE_SELL, "BEARISH"
    return VOTE_NEUTRAL, "NEUTRAL"


class M1Sniper(TimeframeAgent):
    """M1 trigger: micro rejection wick / immediate momentum (zero chase)."""

    id = "TF-M1-Sniper"
    timeframe = "M1"
    min_bars = 2

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=2 M1 bars", timeframe="M1")

        o, h, low, c = b.opens[-1], b.highs[-1], b.lows[-1], b.closes[-1]
        upper, lower, body = wick_stats(o, h, low, c)
        meta: dict[str, Any] = {
            "upper_wick_pct": _pct(upper),
            "lower_wick_pct": _pct(lower),
            "body_pct": _pct(body),
            "close": round(c, 2),
        }

        # Multi-candle momentum context (up to 5 bars)
        window = min(5, b.n)
        recent_reds = sum(1 for i in range(-window, 0) if b.closes[i] < b.opens[i])
        recent_greens = sum(1 for i in range(-window, 0) if b.closes[i] > b.opens[i])

        # 1. Bearish Rejection Wick (shooting star at micro top)
        if upper >= SNIPER_REJECTION and (c < o or body <= SNIPER_THIN_BODY):
            return self.signal(
                vote=VOTE_SELL,
                confidence=0.75,
                reasoning="bearish rejection wick (sniper)",
                metadata={**meta, "rejection": "BEARISH_REJECTION"},
            )

        # 2. Bullish Rejection Wick (hammer at micro bottom)
        if lower >= SNIPER_REJECTION and (c > o or body <= SNIPER_THIN_BODY):
            # If market is experiencing a severe cascade drop (4+ consecutive red candles)
            # and current candle didn't close green, don't blindly buy into a freefall
            if recent_reds >= 4 and c <= o:
                return self.signal(
                    vote=VOTE_NEUTRAL,
                    confidence=0.50,
                    reasoning="damped rejection during heavy M1 cascade",
                    metadata={**meta, "rejection": "DAMPED_REJECTION"},
                )
            return self.signal(
                vote=VOTE_BUY,
                confidence=0.75,
                reasoning="bullish rejection wick (sniper)",
                metadata={**meta, "rejection": "BULLISH_REJECTION"},
            )

        # 3. Two-candle Engulfing Pattern
        if b.n >= 2:
            prev_o, prev_c = b.opens[-2], b.closes[-2]
            # Bullish Engulfing: prev red, current green engulfs prev body
            if prev_c < prev_o and c > o and c >= prev_o and o <= prev_c:
                return self.signal(
                    vote=VOTE_BUY,
                    confidence=0.75,
                    reasoning="bullish engulfing (sniper)",
                    metadata={**meta, "rejection": "BULLISH_ENGULFING"},
                )
            # Bearish Engulfing: prev green, current red engulfs prev body
            if prev_c > prev_o and c < o and c <= prev_o and o >= prev_c:
                return self.signal(
                    vote=VOTE_SELL,
                    confidence=0.75,
                    reasoning="bearish engulfing (sniper)",
                    metadata={**meta, "rejection": "BEARISH_ENGULFING"},
                )

        # 4. Anti-Falling Knife: If 3+ consecutive heavy red candles with red close, vote SELL
        if recent_reds >= 3 and c < o:
            return self.signal(
                vote=VOTE_SELL,
                confidence=0.70,
                reasoning="consecutive bearish momentum (sniper)",
                metadata={**meta, "rejection": "BEARISH_CASCADE"},
            )
        # Anti-Rocket: If 3+ consecutive green candles with green close, vote BUY
        if recent_greens >= 3 and c > o:
            return self.signal(
                vote=VOTE_BUY,
                confidence=0.70,
                reasoning="consecutive bullish momentum (sniper)",
                metadata={**meta, "rejection": "BULLISH_CASCADE"},
            )

        # 5. Standard body direction
        if c > o:
            return self.signal(
                vote=VOTE_BUY,
                confidence=0.60,
                reasoning="bullish body (sniper)",
                metadata={**meta, "rejection": "BULLISH_BODY"},
            )
        if c < o:
            return self.signal(
                vote=VOTE_SELL,
                confidence=0.60,
                reasoning="bearish body (sniper)",
                metadata={**meta, "rejection": "BEARISH_BODY"},
            )
        return self.signal(
            vote=VOTE_NEUTRAL,
            confidence=0.50,
            reasoning="doji (sniper)",
            metadata={**meta, "rejection": "NONE"},
        )


class M5Inspector(TimeframeAgent):
    """M5 setup: displacement geometry (body >= 1.2×ATR) + micro structure."""

    id = "TF-M5-Inspector"
    timeframe = "M5"
    min_bars = 3

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=3 M5 bars", timeframe="M5")

        o, c = b.opens[-1], b.closes[-1]
        body = abs(c - o)
        atr_val = atr(b.highs, b.lows, b.closes, period=14)
        displacement = body >= (M5_DISPLACEMENT_ATR * atr_val)
        meta = {
            "body_size": round(body, 2),
            "atr_m5": round(atr_val, 2),
            "displacement": displacement,
            "close": round(c, 2),
        }

        # Multi-bar micro structure (check support/resistance breaks)
        if b.n >= 6:
            local_support = min(b.lows[-6:-1])
            local_resistance = max(b.highs[-6:-1])
            if c < local_support:
                return self.signal(
                    vote=VOTE_SELL,
                    confidence=0.80 if displacement else 0.70,
                    reasoning="bearish M5 breakdown below support",
                    metadata={**meta, "structure": "BREAKDOWN_SUPPORT"},
                )
            if c > local_resistance:
                return self.signal(
                    vote=VOTE_BUY,
                    confidence=0.80 if displacement else 0.70,
                    reasoning="bullish M5 breakout above resistance",
                    metadata={**meta, "structure": "BREAKOUT_RESISTANCE"},
                )

        if c > o:
            return self.signal(
                vote=VOTE_BUY,
                confidence=0.80 if displacement else 0.60,
                reasoning=f"{'displacement' if displacement else 'bullish'} M5 setup",
                metadata=meta,
            )
        if c < o:
            return self.signal(
                vote=VOTE_SELL,
                confidence=0.80 if displacement else 0.60,
                reasoning=f"{'displacement' if displacement else 'bearish'} M5 setup",
                metadata=meta,
            )
        return self.signal(
            vote=VOTE_NEUTRAL, confidence=0.50, reasoning="flat M5", metadata=meta
        )


class M15Liquidity(TimeframeAgent):
    """M15 liquidity: dynamic EMA 20/50 trend + local BSL/SSL pools."""

    id = "TF-M15-Liquidity"
    timeframe = "M15"
    min_bars = 5

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=5 M15 bars", timeframe="M15")

        c = b.last_close
        ema_fast = ema_last(b.closes, min(20, b.n))
        ema_slow = ema_last(b.closes, min(50, b.n))
        lookback = min(20, b.n)
        bsl = max(b.highs[-lookback:])
        ssl = min(b.lows[-lookback:])
        slope_span = min(4, max(2, b.n // 3))
        vote, bias = _direction_from_ema(c, ema_fast, ema_slow, b.slope(slope_span))

        # Liquidity pool interaction
        if b.n >= 10:
            if c < ssl:
                vote, bias = VOTE_SELL, "BEARISH_BREAKDOWN"
            elif c > bsl:
                vote, bias = VOTE_BUY, "BULLISH_BREAKOUT"

        return self.signal(
            vote=vote,
            confidence=0.75 if vote else 0.50,
            reasoning=f"M15 liquidity {bias} (EMA20/50)",
            metadata={
                "bias": bias,
                "ema_fast": round(ema_fast, 2),
                "ema_slow": round(ema_slow, 2),
                "bsl_pool": round(bsl, 2),
                "ssl_pool": round(ssl, 2),
                "close": round(c, 2),
            },
        )


class M30Momentum(TimeframeAgent):
    """M30 momentum bridge: deceleration / wick absorption exhaustion."""

    id = "TF-M30-Momentum"
    timeframe = "M30"
    min_bars = 3

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=3 M30 bars", timeframe="M30")

        window = min(5, b.n)
        uppers, lowers, bodies = [], [], []
        for i in range(-window, 0):
            upper, lower, body = wick_stats(
                b.opens[i], b.highs[i], b.lows[i], b.closes[i]
            )
            uppers.append(upper)
            lowers.append(lower)
            bodies.append(body)
        avg_upper, avg_lower, avg_body = mean(uppers), mean(lowers), mean(bodies)

        c = b.last_close
        ema_fast = ema_last(b.closes, min(20, b.n))
        meta = {
            "upper_wick_ratio": round(avg_upper, 2),
            "lower_wick_ratio": round(avg_lower, 2),
            "close": round(c, 2),
        }

        if avg_upper >= M30_EXHAUSTION_WICK and avg_body < M30_THIN_BODY:
            return self.signal(
                vote=VOTE_SELL,
                confidence=0.70,
                reasoning="bearish wick exhaustion (M30)",
                metadata={**meta, "exhaustion": "BEARISH_EXHAUSTION"},
            )
        if avg_lower >= M30_EXHAUSTION_WICK and avg_body < M30_THIN_BODY:
            return self.signal(
                vote=VOTE_BUY,
                confidence=0.70,
                reasoning="bullish wick exhaustion (M30)",
                metadata={**meta, "exhaustion": "BULLISH_EXHAUSTION"},
            )
        slope_span = min(3, max(2, b.n // 3))
        vote, bias = _direction_from_ema(c, ema_fast, ema_fast, b.slope(slope_span))
        return self.signal(
            vote=vote,
            confidence=0.65 if vote else 0.50,
            reasoning=f"M30 momentum {bias}",
            metadata={**meta, "exhaustion": "NONE", "bias": bias},
        )


class H1Regime(TimeframeAgent):
    """H1 regime commander: SIDEWAYS vs TRENDING + HTF veto."""

    id = "TF-H1-Regime"
    timeframe = "H1"
    min_bars = 5
    htf = True

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=5 H1 bars", timeframe="H1")

        c = b.last_close
        atr_h1 = atr(b.highs, b.lows, b.closes, period=14)
        lookback = min(24, b.n)
        h1_high = max(b.highs[-lookback:])
        h1_low = min(b.lows[-lookback:])
        h1_range = max(0.5, h1_high - h1_low)

        opens = b.opens[-lookback:]
        closes = b.closes[-lookback:]
        greens = [cl > op for op, cl in zip(opens, closes, strict=False)]
        switches = sum(1 for a, nxt in zip(greens, greens[1:], strict=False) if a != nxt)

        ema_fast = ema_last(b.closes, min(20, max(5, b.n // 2)))
        ema_slow = ema_last(b.closes, min(50, b.n))
        ema_diff = abs(ema_fast - ema_slow)
        slope_span = min(4, max(2, b.n // 4))
        slope3 = b.slope(slope_span)

        trend_switches_max = max(H1_TREND_SWITCHES, int(lookback * 0.25))
        strongly_directional = (
            c >= ema_fast >= ema_slow and switches <= trend_switches_max and slope3 > 0
        ) or (
            c <= ema_fast <= ema_slow and switches <= trend_switches_max and slope3 < 0
        )
        switch_threshold = max(3, int(lookback * 0.4))
        sideways = not strongly_directional and (
            switches >= switch_threshold
            or (h1_range <= H1_FLAT_RANGE and ema_diff < atr_h1 * 0.3)
        )
        regime = "SIDEWAYS" if sideways else "TRENDING"

        veto: str | None = None
        box_fraction = 0.20  # Top/bottom 20% range barrier
        if regime == "SIDEWAYS":
            if c >= h1_high - (box_fraction * h1_range):
                vote, bias, conf = VOTE_SELL, "BEARISH", 0.75
                veto = VETO_BUY  # Anti-pucuk: Dilarang BUY di atap range sideways
            elif c <= h1_low + (box_fraction * h1_range):
                vote, bias, conf = VOTE_BUY, "BULLISH", 0.75
                veto = VETO_SELL  # Anti-dasar: Dilarang SELL di lantai range sideways
            else:
                vote, bias, conf = VOTE_NEUTRAL, "NEUTRAL", 0.50
        else:
            vote, bias = _direction_from_ema(c, ema_fast, ema_slow, slope3)
            conf = 0.80 if vote else 0.50
            if vote == VOTE_BUY:
                veto = VETO_SELL
            elif vote == VOTE_SELL:
                veto = VETO_BUY

        return self.signal(
            vote=vote,
            confidence=conf,
            reasoning=f"H1 regime {regime} bias {bias}" + (f" ({veto})" if veto else ""),
            veto=veto,
            metadata={
                "regime": regime,
                "bias": bias,
                "h1_high": round(h1_high, 2),
                "h1_low": round(h1_low, 2),
                "h1_range": round(h1_range, 2),
                "ema_fast": round(ema_fast, 2),
                "ema_slow": round(ema_slow, 2),
                "atr_h1": round(atr_h1, 2),
                "close": round(c, 2),
            },
        )


class H4Structure(TimeframeAgent):
    """H4 structure architect: major supply/demand blocks + trend."""

    id = "TF-H4-Structure"
    timeframe = "H4"
    min_bars = 5
    htf = True

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=5 H4 bars", timeframe="H4")

        c = b.last_close
        ema_fast = ema_last(b.closes, min(20, b.n))
        ema_slow = ema_last(b.closes, min(50, b.n))
        lookback = min(40, b.n)
        highest = max(b.highs[-lookback:])
        lowest = min(b.lows[-lookback:])
        h4_range = max(1.0, highest - lowest)
        supply_zone_low = highest - (H4_BLOCK_FRACTION * h4_range)
        demand_zone_high = lowest + (H4_BLOCK_FRACTION * h4_range)

        h4_veto_enabled = getattr(default_settings, "h4_entry_veto_enabled", True)
        veto: str | None = None
        if h4_veto_enabled:
            if c >= supply_zone_low:
                veto = VETO_BUY
            elif c <= demand_zone_high:
                veto = VETO_SELL

        slope_span = min(4, max(2, b.n // 4))
        vote, bias = _direction_from_ema(c, ema_fast, ema_slow, b.slope(slope_span))

        # Expose H4 metrics in shared state for downstream position management / adaptive TP
        if state and hasattr(state, "extra") and isinstance(state.extra, dict):
            state.extra["h4_highest"] = round(highest, 2)
            state.extra["h4_lowest"] = round(lowest, 2)
            state.extra["h4_bias"] = bias
            state.extra["h4_supply_low"] = round(supply_zone_low, 2)
            state.extra["h4_demand_high"] = round(demand_zone_high, 2)

        return self.signal(
            vote=vote,
            confidence=0.75 if vote else 0.50,
            reasoning=f"H4 structure {bias}" + (f" ({veto})" if veto else ""),
            veto=veto,
            metadata={
                "bias": bias,
                "ema_fast": round(ema_fast, 2),
                "ema_slow": round(ema_slow, 2),
                "highest_h4": round(highest, 2),
                "lowest_h4": round(lowest, 2),
                "close": round(c, 2),
            },
        )


class D1Macro(TimeframeAgent):
    """D1 macro map: PDH/PDL, equilibrium, extreme-zone veto."""

    id = "TF-D1-Macro"
    timeframe = "D1"
    min_bars = 1
    htf = True

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=1 D1 bar", timeframe="D1")

        c = b.last_close
        prev = -2 if b.n >= 2 else -1
        pdh = b.highs[prev]
        pdl = b.lows[prev]
        macro_range = max(1.0, pdh - pdl)
        equilibrium = round((pdh + pdl) / 2.0, 2)
        premium_thresh = pdh - (D1_EXTREME_FRACTION * macro_range)
        discount_thresh = pdl + (D1_EXTREME_FRACTION * macro_range)

        d1_entry_veto_enabled = getattr(default_settings, "d1_entry_veto_enabled", True)

        veto: str | None = None
        if c >= premium_thresh:
            zone = "EXTREME_PREMIUM"
            if d1_entry_veto_enabled:
                veto = VETO_BUY
        elif c <= discount_thresh:
            zone = "EXTREME_DISCOUNT"
            if d1_entry_veto_enabled:
                veto = VETO_SELL
        elif c >= equilibrium:
            zone = "PREMIUM"
        else:
            zone = "DISCOUNT"

        ema_fast = ema_last(b.closes, min(20, b.n))
        ema_slow = ema_last(b.closes, min(50, b.n))
        slope_span = min(3, max(2, b.n // 2))
        vote, bias = _direction_from_ema(c, ema_fast, ema_slow, b.slope(slope_span))

        # Institutional Top-Down Rule:
        # If D1 macro bias is confirmed BULLISH -> VETO_SELL (strictly no shorts into daily uptrend).
        # If D1 macro bias is confirmed BEARISH -> VETO_BUY (strictly no longs into daily downtrend).
        d1_macro_bias_veto = getattr(default_settings, "d1_macro_bias_veto_enabled", True)
        if veto is None and d1_entry_veto_enabled and d1_macro_bias_veto:
            if bias == "BULLISH" and vote == VOTE_BUY:
                veto = VETO_SELL
            elif bias == "BEARISH" and vote == VOTE_SELL:
                veto = VETO_BUY

        # Expose D1 PDH/PDL metrics in shared state for Macro SL Invalidation
        if state and hasattr(state, "extra") and isinstance(state.extra, dict):
            state.extra["d1_pdh"] = round(pdh, 2)
            state.extra["d1_pdl"] = round(pdl, 2)
            state.extra["d1_bias"] = bias
            state.extra["d1_zone"] = zone

        return self.signal(
            vote=vote,
            confidence=0.80 if vote else 0.50,
            reasoning=f"D1 macro {bias} zone {zone}" + (f" ({veto})" if veto else ""),
            veto=veto,
            metadata={
                "bias": bias,
                "pdh": round(pdh, 2),
                "pdl": round(pdl, 2),
                "equilibrium": equilibrium,
                "macro_range": round(macro_range, 2),
                "zone": zone,
                "close": round(c, 2),
            },
        )


#: Ordered fast -> slow for convenient iteration / registration.
SCOUT_CLASSES: tuple[type[TimeframeAgent], ...] = (
    M1Sniper,
    M5Inspector,
    M15Liquidity,
    M30Momentum,
    H1Regime,
    H4Structure,
    D1Macro,
)


def _self_check() -> None:  # pragma: no cover - import-time contract guard
    for cls in SCOUT_CLASSES:
        assert cls.timeframe, f"{cls.id} must declare a timeframe"
        assert cls.id.startswith("TF-"), f"{cls.id} must use the TF- prefix"


_self_check()


__all__ = [
    "M1Sniper",
    "M5Inspector",
    "M15Liquidity",
    "M30Momentum",
    "H1Regime",
    "H4Structure",
    "D1Macro",
    "SCOUT_CLASSES",
]
