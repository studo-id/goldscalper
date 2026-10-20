"""Market Lifecycle & Regime Detection Engine (GoldScalper).

Classifies market into 4 distinct lifecycle stages:
1. Stage 1: SIDEWAY (Range Consolidation)
   - Flat moving average slopes, bounded volatility, mean-reversion ping-pong.
   - Strict 30/40/30 zones active (VETO_ALL in middle 40%, Ping SELL top 30%, Pong BUY bottom 30%).

2. Stage 2: TRENDING (Breakout / Directional Expansion)
   - Steep EMA slope, progressive swing displacement (BOS, HH/HL or LH/LL).
   - DEAD ZONE IS DISABLED. Veto barriers in trend direction are bypassed.
   - Fast momentum continuation scalping active (AcengGold wave-chaining style).

3. Stage 3: EXHAUSTION (Overextended Trend / Climax)
   - Price stretched > 2.3 ATR from mean, RSI extremes (< 28 or > 72) with rejection wicks or divergence.
   - Trend continuation is BANNED to prevent FOMO entries at peaks/valleys.

4. Stage 4: REVERSAL (Change of Character / CHoCH)
   - Liquidity sweep + structural reversal confirmation (breaking opposite swing with displacement).
   - Direction shifts cleanly; counter-trend entry permitted with tight structural invalidation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.indicators import atr, ema_last, ema_series, rsi_last, wick_stats
from core.market_data import Bars

if TYPE_CHECKING:
    from agents.state import SharedState


REGIME_SIDEWAY = "SIDEWAY"
REGIME_TRENDING_BULL = "TRENDING_BULL"
REGIME_TRENDING_BEAR = "TRENDING_BEAR"
REGIME_EXHAUSTION_BULL = "EXHAUSTION_BULL"
REGIME_EXHAUSTION_BEAR = "EXHAUSTION_BEAR"
REGIME_REVERSAL_BULL = "REVERSAL_BULL"
REGIME_REVERSAL_BEAR = "REVERSAL_BEAR"


@dataclass(frozen=True)
class MarketRegime:
    regime: str
    confidence: float
    description: str
    is_trending: bool
    is_exhausted: bool
    allow_trend_continuation: bool
    allow_dead_zone: bool
    direction: str  # "BUY" | "SELL" | "NEUTRAL"
    m5_slope: float
    m1_span: float
    rsi_m1: float
    distance_from_mean_atr: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "confidence": round(self.confidence, 3),
            "description": self.description,
            "is_trending": self.is_trending,
            "is_exhausted": self.is_exhausted,
            "allow_trend_continuation": self.allow_trend_continuation,
            "allow_dead_zone": self.allow_dead_zone,
            "direction": self.direction,
            "m5_slope": round(self.m5_slope, 3),
            "m1_span": round(self.m1_span, 2),
            "rsi_m1": round(self.rsi_m1, 1),
            "distance_from_mean_atr": round(self.distance_from_mean_atr, 2),
        }


def detect_market_regime(
    state: SharedState,
    cur_price: float | None = None,
) -> MarketRegime:
    """Evaluate M5 and M1 market data to determine the current market lifecycle stage."""
    b_m5 = Bars.for_timeframe(state, "M5")
    b_m1 = Bars.for_timeframe(state, "M1")

    # Fallback if insufficient history
    if b_m5.n < 15 or b_m1.n < 10:
        return MarketRegime(
            regime=REGIME_SIDEWAY,
            confidence=0.50,
            description="Insufficient history for regime classification",
            is_trending=False,
            is_exhausted=False,
            allow_trend_continuation=False,
            allow_dead_zone=True,
            direction="NEUTRAL",
            m5_slope=0.0,
            m1_span=0.0,
            rsi_m1=50.0,
            distance_from_mean_atr=0.0,
        )

    price = cur_price or b_m1.last_close

    # 1. M5 Macro Dynamics (Trend & Distance from Mean)
    ema9_series = ema_series(b_m5.closes, 9)
    ema9 = ema9_series[-1]
    ema21 = ema_last(b_m5.closes, 21)
    slope_m5 = ema9_series[-1] - ema9_series[-3] if len(ema9_series) >= 3 else 0.0
    atr_m5 = max(0.50, atr(b_m5.highs, b_m5.lows, b_m5.closes, 14))
    dist_mean = price - ema9
    dist_atr = abs(dist_mean) / atr_m5

    # 2. M1 Micro Structure & Swings
    lookback_m1 = min(35, b_m1.n - 1)
    m1_highs = b_m1.highs[-lookback_m1 - 1 : -1]
    m1_lows = b_m1.lows[-lookback_m1 - 1 : -1]
    swing_high = max(m1_highs) if m1_highs else price
    swing_low = min(m1_lows) if m1_lows else price
    m1_span = max(0.10, swing_high - swing_low)

    rsi_m1 = rsi_last(b_m1.closes, 14)

    # Candlestick progression (last 3-4 M1 bars)
    last_3_red = b_m1.n >= 3 and all(b_m1.closes[i] < b_m1.opens[i] for i in range(-3, 0))
    last_3_green = b_m1.n >= 3 and all(b_m1.closes[i] > b_m1.opens[i] for i in range(-3, 0))

    bos_bear = price < (swing_low - 0.20)
    bos_bull = price > (swing_high + 0.20)

    # Last bar wick stats
    last_o = b_m1.opens[-1]
    last_h = b_m1.highs[-1]
    last_l = b_m1.lows[-1]
    last_c = b_m1.closes[-1]
    upper_wick, lower_wick, _ = wick_stats(last_o, last_h, last_l, last_c)

    # 3. Stage 3: Trend Exhaustion Checks (Overextended / Climax)
    # Bearish Exhaustion: Active prior downward momentum now overstretched or rejecting
    has_prior_bear_move = (ema9 < ema21 or slope_m5 < -0.05 or dist_mean < -(0.5 * atr_m5))
    if has_prior_bear_move and (
        (dist_mean < -(2.3 * atr_m5) and rsi_m1 < 30)
        or (dist_mean < -(1.5 * atr_m5) and rsi_m1 < 25 and lower_wick > 0.40)
        or (price < swing_low and rsi_m1 > 35 and b_m1.n >= 6 and min(b_m1.lows[-6:-3]) > price)  # divergence hint
    ):
        return MarketRegime(
            regime=REGIME_EXHAUSTION_BEAR,
            confidence=0.80,
            description=f"Bearish trend exhaustion (RSI {rsi_m1:.1f}, {dist_atr:.1f}x ATR from EMA9, lower wick rejection)",
            is_trending=False,
            is_exhausted=True,
            allow_trend_continuation=False,
            allow_dead_zone=False,
            direction="NEUTRAL",
            m5_slope=slope_m5,
            m1_span=m1_span,
            rsi_m1=rsi_m1,
            distance_from_mean_atr=dist_atr,
        )

    # Bullish Exhaustion: Active prior upward momentum now overstretched or rejecting
    has_prior_bull_move = (ema9 > ema21 or slope_m5 > 0.05 or dist_mean > (0.5 * atr_m5))
    if has_prior_bull_move and (
        (dist_mean > (2.3 * atr_m5) and rsi_m1 > 70)
        or (dist_mean > (1.5 * atr_m5) and rsi_m1 > 75 and upper_wick > 0.40)
        or (price > swing_high and rsi_m1 < 65 and b_m1.n >= 6 and max(b_m1.highs[-6:-3]) < price)  # divergence hint
    ):
        return MarketRegime(
            regime=REGIME_EXHAUSTION_BULL,
            confidence=0.80,
            description=f"Bullish trend exhaustion (RSI {rsi_m1:.1f}, {dist_atr:.1f}x ATR from EMA9, upper wick rejection)",
            is_trending=False,
            is_exhausted=True,
            allow_trend_continuation=False,
            allow_dead_zone=False,
            direction="NEUTRAL",
            m5_slope=slope_m5,
            m1_span=m1_span,
            rsi_m1=rsi_m1,
            distance_from_mean_atr=dist_atr,
        )

    # 4. Stage 4: Confirmed Reversal / CHoCH
    # If after deep drop, strong bullish displacement breaks recent M1 swing high
    if dist_mean < -(1.0 * atr_m5) and last_3_green and last_c > b_m1.highs[-3]:
        return MarketRegime(
            regime=REGIME_REVERSAL_BULL,
            confidence=0.75,
            description="Bullish Change of Character (CHoCH): displacement rejecting lower level",
            is_trending=False,
            is_exhausted=False,
            allow_trend_continuation=False,
            allow_dead_zone=False,
            direction="BUY",
            m5_slope=slope_m5,
            m1_span=m1_span,
            rsi_m1=rsi_m1,
            distance_from_mean_atr=dist_atr,
        )

    # If after strong rally, strong bearish displacement breaks recent M1 swing low
    if dist_mean > (1.0 * atr_m5) and last_3_red and last_c < b_m1.lows[-3]:
        return MarketRegime(
            regime=REGIME_REVERSAL_BEAR,
            confidence=0.75,
            description="Bearish Change of Character (CHoCH): displacement rejecting higher level",
            is_trending=False,
            is_exhausted=False,
            allow_trend_continuation=False,
            allow_dead_zone=False,
            direction="SELL",
            m5_slope=slope_m5,
            m1_span=m1_span,
            rsi_m1=rsi_m1,
            distance_from_mean_atr=dist_atr,
        )

    # 5. Stage 2: Confirmed Trend Continuation (Breakout & Impulse Expansion)
    # Require real directional displacement: multi-bar progression, structural breakout (BOS), or active M1 cascade
    m5_bear_progression = b_m5.n >= 3 and (b_m5.closes[-1] < b_m5.closes[-2] < b_m5.closes[-3])
    m5_bull_progression = b_m5.n >= 3 and (b_m5.closes[-1] > b_m5.closes[-2] > b_m5.closes[-3])

    is_bear_trend = (
        (ema9 < ema21 and slope_m5 < -0.10 and (m5_bear_progression or bos_bear or last_3_red))
        or (bos_bear and slope_m5 < 0.0)
        or (last_3_red and slope_m5 < -0.05)
    )
    if is_bear_trend:
        return MarketRegime(
            regime=REGIME_TRENDING_BEAR,
            confidence=0.85,
            description=f"Confirmed Bearish Trend Expansion (EMA9 < EMA21, slope {slope_m5:+.2f}, active impulse)",
            is_trending=True,
            is_exhausted=False,
            allow_trend_continuation=True,
            allow_dead_zone=False,
            direction="SELL",
            m5_slope=slope_m5,
            m1_span=m1_span,
            rsi_m1=rsi_m1,
            distance_from_mean_atr=dist_atr,
        )

    is_bull_trend = (
        (ema9 > ema21 and slope_m5 > 0.10 and (m5_bull_progression or bos_bull or last_3_green))
        or (bos_bull and slope_m5 > 0.0)
        or (last_3_green and slope_m5 > 0.05)
    )
    if is_bull_trend:
        return MarketRegime(
            regime=REGIME_TRENDING_BULL,
            confidence=0.85,
            description=f"Confirmed Bullish Trend Expansion (EMA9 > EMA21, slope {slope_m5:+.2f}, active impulse)",
            is_trending=True,
            is_exhausted=False,
            allow_trend_continuation=True,
            allow_dead_zone=False,
            direction="BUY",
            m5_slope=slope_m5,
            m1_span=m1_span,
            rsi_m1=rsi_m1,
            distance_from_mean_atr=dist_atr,
        )

    # 6. Stage 1: Sideway Murni (Consolidation / Range Squeeze)
    # Slopes are flat, no active expansion, bounded between support and resistance
    return MarketRegime(
        regime=REGIME_SIDEWAY,
        confidence=0.70,
        description=f"Confirmed Sideway Consolidation (flat slope {slope_m5:+.2f}, M1 span ${m1_span:.2f})",
        is_trending=False,
        is_exhausted=False,
        allow_trend_continuation=False,
        allow_dead_zone=True,
        direction="NEUTRAL",
        m5_slope=slope_m5,
        m1_span=m1_span,
        rsi_m1=rsi_m1,
        distance_from_mean_atr=dist_atr,
    )
