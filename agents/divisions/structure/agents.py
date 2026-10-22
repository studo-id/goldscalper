"""Structure division agents.

    5.1 MarketStructure — BOS / CHoCH, swing HL/LH
    5.2 Liquidity       — order blocks, FVG, liquidity sweeps
    5.3 Session         — killzone / Asia-London-NY context (informational)
    5.4 Microstructure  — spread + up/down volume pressure
    5.5 Correlation     — DXY / yields / silver cross-asset bias
"""

from __future__ import annotations

from typing import Any

from agents.base import AgentSignal
from agents.divisions.structure.base import StructureAgent
from agents.state import (
    VETO_BUY,
    VETO_SELL,
    VOTE_BUY,
    VOTE_NEUTRAL,
    VOTE_SELL,
    SharedState,
    utcnow,
)


class MarketStructure(StructureAgent):
    """Break of structure / change of character from recent swings."""

    id = "Struct-MarketStructure"
    timeframe = "M5"
    min_bars = 6

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=6 M5 bars", timeframe="M5")

        k = min(20, max(5, b.n - 1))
        prior_high = max(b.highs[-k - 1 : -1])
        prior_low = min(b.lows[-k - 1 : -1])
        c = b.last_close

        meta: dict[str, Any] = {
            "prior_high": round(prior_high, 2),
            "prior_low": round(prior_low, 2),
            "close": round(c, 2),
        }

        # 1. Break of Structure (BOS)
        if c > prior_high:
            return self.signal(
                vote=VOTE_BUY,
                confidence=0.75,
                reasoning="bullish break of structure",
                metadata={**meta, "event": "BOS_BULL"},
            )
        if c < prior_low:
            return self.signal(
                vote=VOTE_SELL,
                confidence=0.75,
                reasoning="bearish break of structure",
                metadata={**meta, "event": "BOS_BEAR"},
            )

        # 2. Multi-bar Swing Progression (prevents 1-bar fake bounces from triggering HH/HL)
        is_hh_hl = (
            b.highs[-1] > b.highs[-2] > b.highs[-3]
            and b.lows[-1] > b.lows[-2] > b.lows[-3]
        ) if b.n >= 4 else (b.highs[-1] > b.highs[-2] and b.lows[-1] > b.lows[-2])

        is_lh_ll = (
            b.highs[-1] < b.highs[-2] < b.highs[-3]
            and b.lows[-1] < b.lows[-2] < b.lows[-3]
        ) if b.n >= 4 else (b.highs[-1] < b.highs[-2] and b.lows[-1] < b.lows[-2])

        if is_hh_hl:
            return self.signal(
                vote=VOTE_BUY,
                confidence=0.65,
                reasoning="higher-highs / higher-lows swing progression",
                metadata={**meta, "event": "HH_HL"},
            )
        if is_lh_ll:
            return self.signal(
                vote=VOTE_SELL,
                confidence=0.65,
                reasoning="lower-highs / lower-lows swing progression",
                metadata={**meta, "event": "LH_LL"},
            )
        return self.signal(
            vote=VOTE_NEUTRAL,
            confidence=0.50,
            reasoning="no clear structure (range consolidation)",
            metadata={**meta, "event": "RANGE"},
        )


class Liquidity(StructureAgent):
    """Fair-value gaps, order blocks, and liquidity sweeps."""

    id = "Struct-Liquidity"
    timeframe = "M5"
    min_bars = 4

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=4 M5 bars", timeframe="M5")

        bullish_fvg = b.lows[-1] > b.highs[-3]
        bearish_fvg = b.highs[-1] < b.lows[-3]

        lookback = min(25, max(4, b.n - 1))
        prior_low = min(b.lows[-lookback - 1 : -1])
        prior_high = max(b.highs[-lookback - 1 : -1])
        ssl_sweep = b.lows[-1] < prior_low and b.closes[-1] > prior_low
        bsl_sweep = b.highs[-1] > prior_high and b.closes[-1] < prior_high

        # Institutional Order Block Detection (Candle Bodies Only: Open to Close)
        order_block_bull = False
        order_block_bear = False
        ob_bull_body: tuple[float, float] | None = None
        ob_bear_body: tuple[float, float] | None = None
        ob_retest_bull = False
        ob_retest_bear = False

        if b.n >= 5:
            # 1. Immediate Formation (expansion bar rejecting opposite candle)
            order_block_bull = b.closes[-1] > b.highs[-2] and b.closes[-2] < b.opens[-2]
            order_block_bear = b.closes[-1] < b.lows[-2] and b.closes[-2] > b.opens[-2]
            if order_block_bull:
                ob_bull_body = (round(min(b.opens[-2], b.closes[-2]), 2), round(max(b.opens[-2], b.closes[-2]), 2))
            if order_block_bear:
                ob_bear_body = (round(min(b.opens[-2], b.closes[-2]), 2), round(max(b.opens[-2], b.closes[-2]), 2))

            # 2. Return / Retest of recent prior Order Block body zone
            k_ob = min(12, b.n - 2)
            cur_p = b.last_close
            for idx in range(-k_ob, -2):
                # Bullish OB candidate: Red candle followed by multi-bar green displacement
                if b.closes[idx] < b.opens[idx] and b.closes[idx + 1] > b.opens[idx]:
                    top_b = b.opens[idx]
                    bot_b = b.closes[idx]
                    if b.lows[-1] <= top_b and cur_p >= bot_b:
                        ob_retest_bull = True
                        ob_bull_body = (round(bot_b, 2), round(top_b, 2))
                        break

                # Bearish OB candidate: Green candle followed by multi-bar red displacement
                if b.closes[idx] > b.opens[idx] and b.closes[idx + 1] < b.opens[idx]:
                    top_b = b.closes[idx]
                    bot_b = b.opens[idx]
                    if b.highs[-1] >= bot_b and cur_p <= top_b:
                        ob_retest_bear = True
                        ob_bear_body = (round(bot_b, 2), round(top_b, 2))
                        break

        meta = {
            "bullish_fvg": bullish_fvg,
            "bearish_fvg": bearish_fvg,
            "ssl_sweep": ssl_sweep,
            "bsl_sweep": bsl_sweep,
            "order_block_bull": order_block_bull or ob_retest_bull,
            "order_block_bear": order_block_bear or ob_retest_bear,
            "ob_retest_bull": ob_retest_bull,
            "ob_retest_bear": ob_retest_bear,
            "ob_bull_body": ob_bull_body,
            "ob_bear_body": ob_bear_body,
            "lookback": lookback,
            "close": round(b.last_close, 2),
        }

        if bullish_fvg or ssl_sweep or order_block_bull or ob_retest_bull:
            if ssl_sweep:
                reason = "bullish liquidity sweep"
            elif ob_retest_bull:
                reason = "bullish order block body retest"
            elif order_block_bull:
                reason = "bullish order block"
            else:
                reason = "bullish FVG"
            conf = 0.75 if (bullish_fvg and (order_block_bull or ob_retest_bull)) else 0.70
            return self.signal(
                vote=VOTE_BUY,
                confidence=conf,
                reasoning=reason,
                metadata=meta,
            )
        if bearish_fvg or bsl_sweep or order_block_bear or ob_retest_bear:
            if bsl_sweep:
                reason = "bearish liquidity sweep"
            elif ob_retest_bear:
                reason = "bearish order block body retest"
            elif order_block_bear:
                reason = "bearish order block"
            else:
                reason = "bearish FVG"
            conf = 0.75 if (bearish_fvg and (order_block_bear or ob_retest_bear)) else 0.70
            return self.signal(
                vote=VOTE_SELL,
                confidence=conf,
                reasoning=reason,
                metadata=meta,
            )
        return self.signal(
            vote=VOTE_NEUTRAL,
            confidence=0.50,
            reasoning="no liquidity signal",
            metadata=meta,
        )


class Session(StructureAgent):
    """Session Trend & Character Scout (GANAS CERDAS).
    
    Tracks session-level momentum, Asian range boundaries, and detects
    violent session waterfalls/rockets to veto suicidal counter-trend entries.
    """

    id = "Struct-Session"
    timeframe = None

    async def evaluate(self, state: SharedState) -> AgentSignal:
        killzone = state.flag("killzone", None)
        session_name = (state.session or "unknown").lower()
        liquid = not state.is_low_liquidity()

        # Check available bars (prefer M15, fallback to M5)
        bars_m15 = state.frames.get("M15")
        bars_m5 = state.frames.get("M5")
        bars = bars_m15 or bars_m5

        # Graceful fallback if no candle history is supplied (maintains test compatibility)
        if not bars or len(bars) < 4:
            return self.signal(
                vote=VOTE_NEUTRAL,
                confidence=0.0,
                reasoning=f"session={session_name} killzone={killzone} liquid={liquid}",
                timeframe=None,
                metadata={
                    "session": session_name,
                    "killzone": killzone,
                    "low_liquidity": not liquid,
                    "session_trend": "NEUTRAL",
                },
            )

        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        n = len(bars)
        lookback = min(16, n)

        session_open = closes[-lookback]
        cur_price = closes[-1]
        session_high = max(highs[-lookback:])
        session_low = min(lows[-lookback:])
        session_range = max(1.0, session_high - session_low)
        delta_open = round(cur_price - session_open, 2)
        slope = closes[-1] - closes[-3] if n >= 3 else 0.0

        # --- ASIAN RANGE BOX & PRE-LONDON CHARACTER MAPPING ---
        now_dt = state.ts if hasattr(state, "ts") and state.ts else utcnow()
        cur_utc_hour = now_dt.hour if hasattr(now_dt, "hour") else 0

        # Filter bars belonging to Asian session today (00:00 - 06:00 UTC)
        asian_bars = [
            b for b in bars
            if getattr(b, "time", None) and hasattr(b.time, "hour")
            and b.time.date() == now_dt.date()
            and 0 <= b.time.hour < 6
        ]

        asian_high = None
        asian_low = None
        asian_span = None
        if asian_bars:
            asian_high = max(b.high for b in asian_bars)
            asian_low = min(b.low for b in asian_bars)
            asian_span = max(1.0, asian_high - asian_low)
            state.extra["asian_high"] = round(asian_high, 2)
            state.extra["asian_low"] = round(asian_low, 2)
            state.extra["asian_span"] = round(asian_span, 2)
            if asian_span < 12.0:
                state.extra["session_expansion_prime"] = True

        meta: dict[str, Any] = {
            "session": session_name,
            "killzone": killzone,
            "low_liquidity": not liquid,
            "session_open": round(session_open, 2),
            "session_high": round(session_high, 2),
            "session_low": round(session_low, 2),
            "session_range": round(session_range, 2),
            "delta_open": delta_open,
        }
        if asian_high is not None and asian_low is not None and asian_span is not None:
            meta["asian_high"] = round(asian_high, 2)
            meta["asian_low"] = round(asian_low, 2)
            meta["asian_span"] = round(asian_span, 2)

        # 0. PRE-LONDON JUDAS SWING LIQUIDITY SWEEP (13:00 - 15:00 WIB / 06:00 - 08:00 UTC)
        # Prevents costly fake-breakout chasing during pre-market liquidity hunts
        if 6 <= cur_utc_hour < 8 and asian_high is not None and asian_low is not None:
            last_bar = bars[-1]
            probe_high = last_bar.high - asian_high
            probe_low = asian_low - last_bar.low
            is_bearish_rejection = (last_bar.close < last_bar.open) or (cur_price <= asian_high + 0.30)
            is_bullish_rejection = (last_bar.close > last_bar.open) or (cur_price >= asian_low - 0.30)

            # Bearish Judas Sweep: Price probed above Asian High (0.10 to 3.50 USD), but rejected -> VETO BUY, VOTE SELL
            if 0.10 <= probe_high <= 3.50 and is_bearish_rejection and cur_price <= asian_high + 0.50:
                meta["session_trend"] = "JUDAS_SWEEP_BEAR"
                state.extra["judas_sweep_bear"] = True
                return self.signal(
                    vote=VOTE_SELL,
                    confidence=0.85,
                    reasoning=f"PRE-LONDON JUDAS SWEEP: Asian High swept (${asian_high:.1f} +${probe_high:.2f}), fake breakout rejected -> veto BUY",
                    veto=VETO_BUY,
                    timeframe=None,
                    metadata={**meta, "sweep_delta": round(probe_high, 2)},
                )

            # Bullish Judas Sweep: Price probed below Asian Low (0.10 to 3.50 USD), but rejected -> VETO SELL, VOTE BUY
            if 0.10 <= probe_low <= 3.50 and is_bullish_rejection and cur_price >= asian_low - 0.50:
                meta["session_trend"] = "JUDAS_SWEEP_BULL"
                state.extra["judas_sweep_bull"] = True
                return self.signal(
                    vote=VOTE_BUY,
                    confidence=0.85,
                    reasoning=f"PRE-LONDON JUDAS SWEEP: Asian Low swept (${asian_low:.1f} -${probe_low:.2f}), fake breakdown rejected -> veto SELL",
                    veto=VETO_SELL,
                    timeframe=None,
                    metadata={**meta, "sweep_delta": round(probe_low, 2)},
                )

        # 1. WATERFALL DOWNTREND (Drop >= $8.00 with negative slope across M15 window)
        # -> VETO BUY: Prevent catching falling knives during strong session selloffs!
        if delta_open <= -8.00 and slope < 0:
            meta["session_trend"] = "WATERFALL_BEAR"
            state.extra["session_waterfall_bear"] = True
            return self.signal(
                vote=VOTE_SELL,
                confidence=0.85,
                reasoning=f"{session_name.upper()} waterfall crash (-${abs(delta_open):.1f} from open), veto BUY",
                veto=VETO_BUY,
                timeframe=None,
                metadata=meta,
            )

        # 2. ROCKET UPTREND (Rally >= $8.00 with positive slope across M15 window)
        # -> VETO SELL: Prevent counter-trend shorting into strong vertical spikes!
        if delta_open >= 8.00 and slope > 0:
            meta["session_trend"] = "ROCKET_BULL"
            state.extra["session_waterfall_bull"] = True
            return self.signal(
                vote=VOTE_BUY,
                confidence=0.85,
                reasoning=f"{session_name.upper()} rocket rally (+${delta_open:.1f} from open), veto SELL",
                veto=VETO_SELL,
                timeframe=None,
                metadata=meta,
            )

        # 3. ASIAN / SIDEWAYS SESSION RANGE (mean-reversion ping-pong)
        if session_name in ("tokyo", "asia", "sydney") or session_range < 6.0:
            meta["session_trend"] = "ASIA_RANGE"
            state.extra["sideways_range"] = True
            state.extra["sr_support"] = session_low
            state.extra["sr_resistance"] = session_high
            session_mid = (session_high + session_low) / 2.0
            state.extra["sr_midline"] = session_mid

            # Extreme Roof (upper 20%): SELL signal + VETO BUY
            if cur_price >= session_high - (0.20 * session_range):
                return self.signal(
                    vote=VOTE_SELL,
                    confidence=0.80,
                    reasoning=f"{session_name.upper()} at session ceiling (${session_high:.1f}), veto BUY",
                    veto=VETO_BUY,
                    timeframe=None,
                    metadata=meta,
                )
            # Extreme Floor (lower 20%): BUY signal + VETO SELL
            if cur_price <= session_low + (0.20 * session_range):
                return self.signal(
                    vote=VOTE_BUY,
                    confidence=0.80,
                    reasoning=f"{session_name.upper()} at session floor (${session_low:.1f}), veto SELL",
                    veto=VETO_SELL,
                    timeframe=None,
                    metadata=meta,
                )
            # Mid-Range (inner 60%): Allow active micro-scalping! Neutral bias without locking veto
            return self.signal(
                vote=VOTE_BUY if slope > 0 else (VOTE_SELL if slope < 0 else VOTE_NEUTRAL),
                confidence=0.45,
                reasoning=f"{session_name.upper()} range mid-zone (${cur_price:.1f}), scalping permitted",
                timeframe=None,
                metadata=meta,
            )

        # 4. MODERATE SESSION DRIFT (London / NY standard flow)
        if delta_open >= 1.50:
            meta["session_trend"] = "MODERATE_BULL"
            return self.signal(
                vote=VOTE_BUY,
                confidence=0.60,
                reasoning=f"{session_name.upper()} session bullish drift (+${delta_open:.1f})",
                timeframe=None,
                metadata=meta,
            )
        if delta_open <= -1.50:
            meta["session_trend"] = "MODERATE_BEAR"
            return self.signal(
                vote=VOTE_SELL,
                confidence=0.60,
                reasoning=f"{session_name.upper()} session bearish drift (-${abs(delta_open):.1f})",
                timeframe=None,
                metadata=meta,
            )

        meta["session_trend"] = "BALANCED"
        return self.signal(
            vote=VOTE_NEUTRAL,
            confidence=0.50,
            reasoning=f"{session_name.upper()} session balanced around open",
            timeframe=None,
            metadata=meta,
        )


class Microstructure(StructureAgent):
    """Order-flow pressure from up/down bar volume, guarded by spread."""

    id = "Struct-Microstructure"
    timeframe = "M1"
    min_bars = 5

    async def evaluate(self, state: SharedState) -> AgentSignal:
        b = self.bars(state)
        if b.n < self.min_bars:
            return self.neutral("need >=5 M1 bars", timeframe="M1")

        n = min(20, b.n)
        up = 0.0
        down = 0.0
        for i in range(-n, 0):
            vol = b.volumes[i] if b.volumes else 1.0
            weight = vol if vol else 1.0
            if b.closes[i] > b.opens[i]:
                up += weight
            elif b.closes[i] < b.opens[i]:
                down += weight

        spread = state.spread_points
        wide = spread is not None and spread > state.flag("max_spread_points", 45)
        conf = 0.60 if not wide else 0.40
        meta = {
            "up_volume": round(up, 2),
            "down_volume": round(down, 2),
            "spread_points": spread,
            "close": round(b.last_close, 2),
        }

        if up > down * 1.2:
            return self.signal(
                vote=VOTE_BUY, confidence=conf, reasoning="buy-side pressure", metadata=meta
            )
        if down > up * 1.2:
            return self.signal(
                vote=VOTE_SELL, confidence=conf, reasoning="sell-side pressure", metadata=meta
            )
        return self.signal(
            vote=VOTE_NEUTRAL, confidence=0.50, reasoning="balanced pressure", metadata=meta
        )


class Correlation(StructureAgent):
    """Cross-asset bias: DXY (inverse), US yields (inverse), silver (direct)."""

    id = "Struct-Correlation"
    timeframe = None

    async def evaluate(self, state: SharedState) -> AgentSignal:
        dxy = state.extra.get("dxy_delta")
        yields = state.extra.get("yields_delta")
        silver = state.extra.get("silver_delta")
        if dxy is None and yields is None and silver is None:
            return self.neutral("no cross-asset data", timeframe=None)

        score = 0
        if dxy is not None:
            score += -1 if dxy > 0 else (1 if dxy < 0 else 0)
        if yields is not None:
            score += -1 if yields > 0 else (1 if yields < 0 else 0)
        if silver is not None:
            score += 1 if silver > 0 else (-1 if silver < 0 else 0)

        if score > 0:
            vote, bias = VOTE_BUY, "bullish"
        elif score < 0:
            vote, bias = VOTE_SELL, "bearish"
        else:
            vote, bias = VOTE_NEUTRAL, "neutral"

        return self.signal(
            vote=vote,
            confidence=0.60 if vote else 0.50,
            reasoning=f"cross-asset {bias} (score {score})",
            timeframe=None,
            metadata={
                "dxy_delta": dxy,
                "yields_delta": yields,
                "silver_delta": silver,
                "score": score,
            },
        )


STRUCTURE_AGENT_CLASSES: tuple[type[StructureAgent], ...] = (
    MarketStructure,
    Liquidity,
    Session,
    Microstructure,
    Correlation,
)


__all__ = [
    "MarketStructure",
    "Liquidity",
    "Session",
    "Microstructure",
    "Correlation",
    "STRUCTURE_AGENT_CLASSES",
]
