"""Technical division agents (IMPLEMENTATION_PLAN Phase 6.1–6.6).

    6.1 Tech-Trend             — EMA stack + slope
    6.2 Tech-Momentum          — RSI + MACD agreement
    6.3 Tech-Volatility        — ATR / Bollinger-bandwidth regime
    6.4 Tech-Volume            — tick-volume / delta proxy
    6.5 Tech-SupportResistance — swing pivots + proximity
    6.6 Tech-Pattern           — engulfing / pin-bar patterns
"""

from __future__ import annotations

from typing import Any

from agents.base import AgentSignal
from agents.divisions.technical.base import TechnicalAgent
from agents.state import VETO_ALL, VETO_BUY, VETO_SELL, VOTE_BUY, VOTE_NEUTRAL, VOTE_SELL, SharedState
from config.settings import Settings, settings as default_settings
from core.indicators import atr, bollinger, ema_last, ema_series, macd, mean, rsi_last, wick_stats
from core.market_regime import (
    REGIME_EXHAUSTION_BEAR,
    REGIME_EXHAUSTION_BULL,
    REGIME_REVERSAL_BEAR,
    REGIME_REVERSAL_BULL,
    REGIME_SIDEWAY,
    REGIME_TRENDING_BEAR,
    REGIME_TRENDING_BULL,
    detect_market_regime,
)


class Trend(TechnicalAgent):
    id = "Tech-Trend"
    timeframe = "M5"
    min_bars = 21
    fast = 9
    slow = 21

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=21 M5 bars", timeframe="M5")
        fast_series = ema_series(b.closes, self.fast)
        fast = fast_series[-1]
        slow = ema_last(b.closes, self.slow)
        slope = fast_series[-1] - fast_series[-3]
        meta = {
            "ema_fast": round(fast, 2),
            "ema_slow": round(slow, 2),
            "slope": round(slope, 3),
            "close": round(b.last_close, 2),
        }
        if fast > slow and slope > 0:
            return self.signal(VOTE_BUY, 0.70, "EMA uptrend with positive slope", meta)
        if fast < slow and slope < 0:
            return self.signal(VOTE_SELL, 0.70, "EMA downtrend with negative slope", meta)
        return self.signal(VOTE_NEUTRAL, 0.50, "EMA trend indecision", meta)


class Momentum(TechnicalAgent):
    id = "Tech-Momentum"
    timeframe = "M5"
    min_bars = 26
    period = 14

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=26 M5 bars", timeframe="M5")
        rsi = rsi_last(b.closes, self.period)
        _, _, hist = macd(b.closes)
        meta = {"rsi": round(rsi, 2), "macd_hist": round(hist, 4)}

        rsi_sig = 1 if rsi > 52 else -1 if rsi < 48 else 0
        macd_sig = 1 if hist > 0 else -1 if hist < 0 else 0
        if rsi_sig == 1 and macd_sig == 1:
            return self.signal(VOTE_BUY, 0.70, "RSI + MACD bullish agreement", meta)
        if rsi_sig == -1 and macd_sig == -1:
            return self.signal(VOTE_SELL, 0.70, "RSI + MACD bearish agreement", meta)
        return self.signal(VOTE_NEUTRAL, 0.50, "momentum mixed", meta)


class Volatility(TechnicalAgent):
    id = "Tech-Volatility"
    timeframe = "M15"
    min_bars = 20
    period = 20
    squeeze_bandwidth = 0.004

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=20 M15 bars", timeframe="M15")
        atr_val = atr(b.highs, b.lows, b.closes, self.period)
        _, _, _, _, bandwidth = bollinger(b.closes, self.period)
        if bandwidth < self.squeeze_bandwidth:
            regime = "squeeze"
            conf = 0.70
            state.extra["volatility_squeeze"] = True
        elif bandwidth > self.squeeze_bandwidth * 3:
            regime = "expansion"
            conf = 0.60
            state.extra["volatility_expansion"] = True
        else:
            regime = "normal"
            conf = 0.50
        meta = {
            "atr": round(atr_val, 3),
            "bandwidth": round(bandwidth, 5),
            "regime": regime,
        }
        return self.signal(VOTE_NEUTRAL, conf, f"volatility regime {regime}", meta, timeframe="M15")


class Volume(TechnicalAgent):
    id = "Tech-Volume"
    timeframe = "M5"
    min_bars = 21
    lookback = 20
    rvol_trigger = 1.5

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=21 M5 bars", timeframe="M5")
        vols = b.volumes
        last_vol = vols[-1]
        baseline = mean(vols[-self.lookback - 1 : -1])
        rvol = (last_vol / baseline) if baseline > 0 else 0.0
        up = b.closes[-1] > b.opens[-1]
        meta = {
            "rvol": round(rvol, 2),
            "volume": round(last_vol, 2),
            "baseline": round(baseline, 2),
        }
        if rvol >= self.rvol_trigger:
            if up:
                return self.signal(VOTE_BUY, 0.65, "high-volume up bar", meta)
            return self.signal(VOTE_SELL, 0.65, "high-volume down bar", meta)
        return self.signal(VOTE_NEUTRAL, 0.50, "volume in line", meta)


class SupportResistance(TechnicalAgent):
    id = "Tech-SupportResistance"
    timeframe = "M5"
    min_bars = 20
    lookback = 20
    proximity = 0.0010

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.s = settings or default_settings
        self.micro_enabled: bool = getattr(self.s, "micro_sr_veto_enabled", True)
        self.micro_lookback: int = getattr(self.s, "micro_sr_lookback_m1", 20)
        self.confirm_range_usd: float = getattr(self.s, "micro_sr_confirm_range_usd", 1.20)
        self.dead_zone_enabled: bool = getattr(self.s, "micro_sr_dead_zone_enabled", False)
        self.dead_zone_max_span: float = getattr(self.s, "micro_sr_dead_zone_max_span", 12.00)
        self.exhaustion_veto_enabled: bool = getattr(self.s, "micro_sr_exhaustion_veto_enabled", True)
        self.aggressive: bool = getattr(self.s, "aggressive_scalper", False)

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=20 M5 bars", timeframe="M5")
        window = slice(-self.lookback, None)
        sorted_lows = sorted(b.lows[window])
        sorted_highs = sorted(b.highs[window])

        # If lowest low is an isolated flash spike (> $4.00 below 2nd lowest), use 2nd lowest as structural floor
        support = (
            sorted_lows[1]
            if (len(sorted_lows) >= 2 and (sorted_lows[1] - sorted_lows[0]) >= 4.0)
            else sorted_lows[0]
        )
        # If highest high is an isolated flash spike (> $4.00 above 2nd highest), use 2nd highest as structural ceiling
        resistance = (
            sorted_highs[-2]
            if (len(sorted_highs) >= 2 and (sorted_highs[-1] - sorted_highs[-2]) >= 4.0)
            else sorted_highs[-1]
        )

        close = b.last_close
        thr = self.proximity * close
        range_span = max(0.1, resistance - support)
        range_pct = range_span / close if close else 0.0
        # Confirmed sideway if range <= $10.00 USD on Gold or range_pct <= 0.008
        sideways = (range_span <= 10.00) or (range_pct <= 0.008)
        midline = (support + resistance) / 2.0

        meta: dict[str, Any] = {
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "raw_support": round(sorted_lows[0], 2),
            "raw_resistance": round(sorted_highs[-1], 2),
            "midline": round(midline, 2),
            "close": round(close, 2),
            "threshold": round(thr, 3),
            "range_span": round(range_span, 2),
            "sideways_range": sideways,
        }

        # --- M1 Local Micro-SR & Strict 3-Zone Anti-Chasing Veto Protection ---
        # Detects local swing lows and swing highs on M1 within the recent lookback window.
        # Divides M1 range into 3 strict zones (30% Support Pong / 40% Dead Zone / 30% Resistance Ping)
        # to prevent chasing entries in the choppy mid-channel.
        if self.micro_enabled:
            b_m1 = self.bars(state, "M1")
            if b_m1.n >= 10:
                close = b_m1.last_close
                meta["close"] = round(close, 2)
                lb = min(b_m1.n - 1, self.micro_lookback)
                prior_lows = b_m1.lows[-lb - 1 : -1] if lb >= 2 else b_m1.lows
                prior_highs = b_m1.highs[-lb - 1 : -1] if lb >= 2 else b_m1.highs
                m1_support = min(prior_lows)
                m1_resistance = max(prior_highs)
                buf = float(self.confirm_range_usd)
                m1_span = max(0.1, m1_resistance - m1_support)
                pos_pct = max(0.0, min(1.0, (close - m1_support) / m1_span))

                meta["m1_support"] = round(m1_support, 2)
                meta["m1_resistance"] = round(m1_resistance, 2)
                meta["m1_span"] = round(m1_span, 2)
                meta["m1_pos_pct"] = round(pos_pct, 3)
                meta["confirm_range_usd"] = round(buf, 2)

                if hasattr(state, "extra") and isinstance(state.extra, dict):
                    state.extra["m1_support"] = m1_support
                    state.extra["m1_resistance"] = m1_resistance
                    state.extra["m1_span"] = m1_span
                    state.extra["m1_pos_pct"] = pos_pct
                    state.extra["m1_confirm_range_usd"] = buf

                # Determine Market Lifecycle Stage & Regime (4-Phase Engine)
                regime = detect_market_regime(state, close)
                meta["market_regime"] = regime.regime
                meta["regime_desc"] = regime.description
                if hasattr(state, "extra") and isinstance(state.extra, dict):
                    state.extra["market_regime"] = regime.regime
                    state.extra["market_regime_info"] = regime.to_dict()
                    state.extra["m1_micro_vote"] = regime.m1_micro_vote
                    state.extra["m5_micro_vote"] = regime.m5_micro_vote
                    state.extra["micro_exhaustion"] = regime.micro_exhaustion

                # 0. Micro-Exhaustion Protection (AcengGold-grade pullback timing guard)
                # When in bear trend: if M1 & M5 are both bouncing bullish, veto continuation SELL at valley bottom
                if self.exhaustion_veto_enabled and regime.micro_exhaustion == "BULLISH_BOUNCE" and (regime.regime == REGIME_TRENDING_BEAR or regime.direction == "SELL"):
                    meta["micro_sr_event"] = "MICRO_EXHAUSTION_BOUNCE"
                    return self.signal(
                        VOTE_NEUTRAL,
                        0.75,
                        f"micro-exhaustion active (M1+M5 bullish bounce), veto SELL [{regime.description}]",
                        meta,
                        veto=VETO_SELL,
                    )
                # When in bull trend: if M1 & M5 are both dipping bearish, veto continuation BUY at mountain peak
                if self.exhaustion_veto_enabled and regime.micro_exhaustion == "BEARISH_DIP" and (regime.regime == REGIME_TRENDING_BULL or regime.direction == "BUY"):
                    meta["micro_sr_event"] = "MICRO_EXHAUSTION_DIP"
                    return self.signal(
                        VOTE_NEUTRAL,
                        0.75,
                        f"micro-exhaustion active (M1+M5 bearish dip), veto BUY [{regime.description}]",
                        meta,
                        veto=VETO_BUY,
                    )

                # 1. Confirmed M1 Breakout / Breakdown (Must genuinely close beyond boundary buffer)
                if close < (m1_support - buf):
                    if close <= (support + buf) and b.last_close >= support and not (regime.is_trending and regime.direction == "SELL"):
                        meta["micro_sr_event"] = "M5_SUPPORT_COLLISION"
                        return self.signal(
                            VOTE_NEUTRAL,
                            0.80,
                            f"M1 micro-breakdown colliding into M5 support floor (${support:.2f}), veto SELL",
                            meta,
                            veto=VETO_SELL,
                        )
                    meta["micro_sr_event"] = "CONFIRMED_MICRO_BREAKDOWN"
                    return self.signal(
                        VOTE_SELL,
                        0.85 if regime.is_trending else 0.80,
                        f"confirmed breakdown below micro-support (${m1_support:.2f} - ${buf:.2f}) [{regime.description}]",
                        meta,
                        veto=VETO_BUY,  # Strictly forbid buying against active breakdown!
                    )
                if close > (m1_resistance + buf):
                    if close >= (resistance - buf) and b.last_close <= resistance and not (regime.is_trending and regime.direction == "BUY"):
                        meta["micro_sr_event"] = "M5_RESISTANCE_COLLISION"
                        return self.signal(
                            VOTE_NEUTRAL,
                            0.80,
                            f"M1 micro-breakout colliding into M5 resistance ceiling (${resistance:.2f}), veto BUY",
                            meta,
                            veto=VETO_BUY,
                        )
                    meta["micro_sr_event"] = "CONFIRMED_MICRO_BREAKOUT"
                    return self.signal(
                        VOTE_BUY,
                        0.85 if regime.is_trending else 0.80,
                        f"confirmed breakout above micro-resistance (${m1_resistance:.2f} + ${buf:.2f}) [{regime.description}]",
                        meta,
                        veto=VETO_SELL,  # Strictly forbid selling against active breakout!
                    )

                # 2. Stage 3: Trend Exhaustion (Overextended - Banned from chasing bottom/top)
                if regime.regime == REGIME_EXHAUSTION_BEAR:
                    meta["micro_sr_event"] = "EXHAUSTION_BEAR_FLOOR"
                    return self.signal(
                        VOTE_NEUTRAL,
                        0.75,
                        f"bearish trend exhausted at floor (${close:.2f}), veto SELL ({regime.description})",
                        meta,
                        veto=VETO_SELL,
                    )
                if regime.regime == REGIME_EXHAUSTION_BULL:
                    meta["micro_sr_event"] = "EXHAUSTION_BULL_CEILING"
                    return self.signal(
                        VOTE_NEUTRAL,
                        0.75,
                        f"bullish trend exhausted at ceiling (${close:.2f}), veto BUY ({regime.description})",
                        meta,
                        veto=VETO_BUY,
                    )

                # 3. Stage 4: Confirmed Reversal / CHoCH
                if regime.regime == REGIME_REVERSAL_BULL:
                    meta["micro_sr_event"] = "REVERSAL_CHOCH_BULL"
                    return self.signal(
                        VOTE_BUY,
                        0.80,
                        f"confirmed bullish CHoCH reversal from floor (${close:.2f}), veto SELL",
                        meta,
                        veto=VETO_SELL,
                    )
                if regime.regime == REGIME_REVERSAL_BEAR:
                    meta["micro_sr_event"] = "REVERSAL_CHOCH_BEAR"
                    return self.signal(
                        VOTE_SELL,
                        0.80,
                        f"confirmed bearish CHoCH reversal from ceiling (${close:.2f}), veto BUY",
                        meta,
                        veto=VETO_BUY,
                    )

                # 4. Active Trend Continuation in Mid/Upper Channel (When Trending, Dead-Zone is SHUT OFF!)
                if regime.is_trending and regime.allow_trend_continuation:
                    bar_idx = -1 if b_m1.n >= 1 else 0
                    last_o = b_m1.opens[bar_idx]
                    last_h = b_m1.highs[bar_idx]
                    last_l = b_m1.lows[bar_idx]
                    last_c = b_m1.closes[bar_idx]
                    c_span = max(0.01, last_h - last_l)

                    if regime.direction == "SELL":
                        l_wick = max(0.0, min(last_o, last_c) - last_l)
                        has_support_rejection = (l_wick / c_span) >= 0.40 and close <= (m1_support + buf)

                        if has_support_rejection:
                            meta["micro_sr_event"] = "TREND_BLOCKED_AT_SUPPORT"
                            return self.signal(
                                VOTE_NEUTRAL,
                                0.80,
                                f"bearish trend expansion rejected at M1 support (lower wick {l_wick/c_span*100:.0f}% >= 40%), veto SELL until breakdown",
                                meta,
                                veto=VETO_SELL,
                            )
                        if pos_pct <= 0.35:
                            meta["micro_sr_event"] = "TREND_SELL_BLOCKED_AT_FLOOR"
                            return self.signal(
                                VOTE_NEUTRAL,
                                0.80,
                                f"trend continuation SELL prohibited near range floor ({pos_pct*100:.1f}% <= 35% of M1 span), veto SELL until confirmed breakdown",
                                meta,
                                veto=VETO_SELL,
                            )
                        meta["micro_sr_event"] = "TREND_CONTINUATION_SELL"
                        return self.signal(
                            VOTE_SELL,
                            0.80,
                            f"trend continuation SELL riding bearish impulse ({regime.description})",
                            meta,
                            veto=VETO_BUY,  # Disallow buying against the active wave
                        )
                    if regime.direction == "BUY":
                        u_wick = max(0.0, last_h - max(last_o, last_c))
                        has_resistance_rejection = (u_wick / c_span) >= 0.40 and close >= (m1_resistance - buf)

                        if has_resistance_rejection:
                            meta["micro_sr_event"] = "TREND_BLOCKED_AT_RESISTANCE"
                            return self.signal(
                                VOTE_NEUTRAL,
                                0.80,
                                f"bullish trend expansion rejected at M1 resistance (upper wick {u_wick/c_span*100:.0f}% >= 40%), veto BUY until breakout",
                                meta,
                                veto=VETO_BUY,
                            )
                        if pos_pct >= 0.65:
                            meta["micro_sr_event"] = "TREND_BUY_BLOCKED_AT_CEILING"
                            return self.signal(
                                VOTE_NEUTRAL,
                                0.80,
                                f"trend continuation BUY prohibited near range ceiling ({pos_pct*100:.1f}% >= 65% of M1 span), veto BUY until confirmed breakout",
                                meta,
                                veto=VETO_BUY,
                            )
                        meta["micro_sr_event"] = "TREND_CONTINUATION_BUY"
                        return self.signal(
                            VOTE_BUY,
                            0.80,
                            f"trend continuation BUY riding bullish impulse ({regime.description})",
                            meta,
                            veto=VETO_SELL,  # Disallow selling against the active wave
                        )

                # 5. Stage 1: Sideway Murni (Range Consolidation)
                # Lower 30% (Support Pong Zone):
                if pos_pct <= 0.30 or (m1_support - buf) <= close <= (m1_support + buf):
                    meta["micro_sr_event"] = "AT_MICRO_SUPPORT"
                    return self.signal(
                        VOTE_BUY,
                        0.80,
                        f"price in M1 lower support zone (${m1_support:.2f} +/- ${buf:.2f}, {pos_pct*100:.1f}%), veto SELL",
                        meta,
                        veto=VETO_SELL,
                    )

                # Upper 30% (Resistance Ping Zone):
                if pos_pct >= 0.70 or (m1_resistance - buf) <= close <= (m1_resistance + buf):
                    meta["micro_sr_event"] = "AT_MICRO_RESISTANCE"
                    return self.signal(
                        VOTE_SELL,
                        0.80,
                        f"price in M1 upper resistance zone (${m1_resistance:.2f} +/- ${buf:.2f}, {pos_pct*100:.1f}%), veto BUY",
                        meta,
                        veto=VETO_BUY,
                    )

                # Middle 40% (Dead / No-Trade Zone) — ONLY in Genuine Sideway!
                if self.dead_zone_enabled and regime.allow_dead_zone:
                    meta["micro_sr_event"] = "M1_MID_DEAD_ZONE"
                    if hasattr(state, "extra") and isinstance(state.extra, dict):
                        state.extra["m1_dead_zone"] = True
                    return self.signal(
                        VOTE_NEUTRAL,
                        0.85,
                        f"price in M1 mid-range dead zone ({pos_pct*100:.1f}% of ${m1_span:.2f} range: ${m1_support:.2f} - ${m1_resistance:.2f}), veto all entries",
                        meta,
                        veto=VETO_ALL,
                    )

        if sideways:
            state.extra["sideways_range"] = True
            state.extra["sr_support"] = support
            state.extra["sr_resistance"] = resistance
            state.extra["sr_midline"] = midline

            # 1. PING: Support zone
            if close < (support - thr):
                # Breakdown through support floor: follow momentum short
                return self.signal(
                    VOTE_SELL,
                    0.80,
                    f"sideway support breakdown (${support:.1f}), follow short momentum",
                    meta,
                )
            if close <= support + (0.25 * range_span):
                return self.signal(
                    VOTE_BUY,
                    0.80,
                    f"sideway bounce at support (${support:.1f}), veto SELL",
                    meta,
                    veto=VETO_SELL,
                )
            # 2. PONG: Resistance zone
            if close > (resistance + thr):
                # Breakout through resistance ceiling: follow momentum long
                return self.signal(
                    VOTE_BUY,
                    0.80,
                    f"sideway resistance breakout (${resistance:.1f}), follow long momentum",
                    meta,
                )
            if close >= resistance - (0.25 * range_span):
                return self.signal(
                    VOTE_SELL,
                    0.80,
                    f"sideway rejection at resistance (${resistance:.1f}), veto BUY",
                    meta,
                    veto=VETO_BUY,
                )
            # 3. Mid-Channel (inner 50%):
            # Allow active scalper flow without blocking vetoes!
            bias_vote = VOTE_BUY if close > midline else (VOTE_SELL if close < midline else VOTE_NEUTRAL)
            return self.signal(
                bias_vote,
                0.40,
                f"sideway mid-channel (${close:.1f}), scalping permitted",
                meta,
            )

        if close - support <= thr:
            return self.signal(VOTE_BUY, 0.65, "price at support", meta)
        if resistance - close <= thr:
            return self.signal(VOTE_SELL, 0.65, "price at resistance", meta)
        return self.signal(VOTE_NEUTRAL, 0.50, "price between levels", meta)


class Pattern(TechnicalAgent):
    id = "Tech-Pattern"
    timeframe = "M5"
    min_bars = 3

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=3 M5 bars", timeframe="M5")

        prev_o, prev_h, prev_l, prev_c = b.opens[-2], b.highs[-2], b.lows[-2], b.closes[-2]
        cur_o, cur_h, cur_l, cur_c = b.opens[-1], b.highs[-1], b.lows[-1], b.closes[-1]
        upper, lower, body = wick_stats(cur_o, cur_h, cur_l, cur_c)

        # 1. Classic Engulfing
        bull_engulf = prev_c < prev_o and cur_c > cur_o and cur_c >= prev_o and cur_o <= prev_c
        bear_engulf = prev_c > prev_o and cur_c < cur_o and cur_c <= prev_o and cur_o >= prev_c

        # 2. Pinbar / Rejection Wick (Hammer & Shooting Star)
        pin_bull = (lower >= 0.6 and body <= 0.25) or (
            lower >= 0.45 and upper <= 0.25 and cur_c >= (cur_h + cur_l) / 2
        )
        pin_bear = (upper >= 0.6 and body <= 0.25) or (
            upper >= 0.45 and lower <= 0.25 and cur_c <= (cur_h + cur_l) / 2
        )

        # 3. Tweezers / 2-Bar Rejection
        tweezers_bottom = (
            b.n >= 4
            and abs(cur_l - prev_l) <= (0.0003 * cur_c)
            and lower >= 0.35
            and cur_c > cur_o
        )
        tweezers_top = (
            b.n >= 4
            and abs(cur_h - prev_h) <= (0.0003 * cur_c)
            and upper >= 0.35
            and cur_c < cur_o
        )

        # 4. Context check: are we near Support or Resistance?
        lookback = min(20, b.n)
        recent_low = min(b.lows[-lookback:])
        recent_high = max(b.highs[-lookback:])
        thr = 0.0012 * cur_c
        at_support = (cur_c - recent_low <= thr) or (cur_l - recent_low <= thr * 0.5)
        at_resistance = (recent_high - cur_c <= thr) or (recent_high - cur_h <= thr * 0.5)

        meta: dict[str, Any] = {
            "upper_wick": round(upper, 2),
            "lower_wick": round(lower, 2),
            "body": round(body, 2),
            "at_support": at_support,
            "at_resistance": at_resistance,
        }

        # Confluence: Rejection Pattern at S/R (Ping-Pong Setup)
        if (bull_engulf or pin_bull or tweezers_bottom) and at_support:
            meta["ping_pong_side"] = "BUY"
            return self.signal(
                VOTE_BUY,
                0.80,
                "bullish pinbar/engulfing rejection at support (ping-pong buy)",
                meta,
            )

        if (bear_engulf or pin_bear or tweezers_top) and at_resistance:
            meta["ping_pong_side"] = "SELL"
            return self.signal(
                VOTE_SELL,
                0.80,
                "bearish shooting-star/engulfing rejection at resistance (ping-pong sell)",
                meta,
            )

        # Standard pattern detection away from strict boundary
        if bull_engulf or pin_bull or tweezers_bottom:
            return self.signal(VOTE_BUY, 0.65, "bullish engulfing / hammer", meta)
        if bear_engulf or pin_bear or tweezers_top:
            return self.signal(VOTE_SELL, 0.65, "bearish engulfing / shooting star", meta)

        # Check M1 if M5 has no pattern and M1 is available
        m1_bars = state.frames.get("M1")
        if m1_bars and len(m1_bars) >= 3:
            m1_o = m1_bars[-1].open
            m1_h = m1_bars[-1].high
            m1_l = m1_bars[-1].low
            m1_c = m1_bars[-1].close
            m1_up, m1_low, _ = wick_stats(m1_o, m1_h, m1_l, m1_c)
            if m1_low >= 0.50 and at_support:
                meta["m1_rejection"] = "bullish"
                meta["ping_pong_side"] = "BUY"
                return self.signal(
                    VOTE_BUY, 0.70, "M1 micro-wick rejection at support (ping-pong buy)", meta
                )
            if m1_up >= 0.50 and at_resistance:
                meta["m1_rejection"] = "bearish"
                meta["ping_pong_side"] = "SELL"
                return self.signal(
                    VOTE_SELL, 0.70, "M1 micro-wick rejection at resistance (ping-pong sell)", meta
                )

        return self.signal(VOTE_NEUTRAL, 0.50, "no pattern", meta)


TECHNICAL_AGENT_CLASSES: tuple[type[TechnicalAgent], ...] = (
    Trend,
    Momentum,
    Volatility,
    Volume,
    SupportResistance,
    Pattern,
)


__all__ = [
    "Trend",
    "Momentum",
    "Volatility",
    "Volume",
    "SupportResistance",
    "Pattern",
    "TECHNICAL_AGENT_CLASSES",
]
