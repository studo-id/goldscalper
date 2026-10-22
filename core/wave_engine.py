"""Data-Driven Wave Surfer & Lifecycle Tracker Engine (GoldScalper).

Unlike static max-chain limits, this engine evaluates REAL-TIME MARKET METRICS
to project trend wave capacity, extension health, and broken wave invalidation:

1. Dynamic Wave Capacity (ATR-Extension Based):
   - HEALTHY (Extension <= 1.8x ATR): Trend is young and vigorous -> Rapid chaining permitted.
   - MATURE (1.8x < Extension <= 2.5x ATR): Trend is aging -> Reduce lot multiplier, require tighter entry.
   - EXHAUSTED (Extension > 2.5x ATR): Trend is overextended -> Cease wave expansion entries.

2. Candle Structure Integrity:
   - Tracks Swing Progression (HH/HL for Bull, LH/LL for Bear).
   - If market fails to create new swing displacement or shows >= 40% counter rejection wicks,
     wave momentum is marked DEGRADED.

3. Smart Broken-Wave Cooldown (90s - 120s Scalper Duration):
   - When a trade is cut via dynamic clamp / watchdog (wave broken):
     Arms a focused 90-second cooldown for THAT SPECIFIC DIRECTION.
   - Early Release: If a confirmed Break of Structure (BOS) or Reversal (CHoCH) occurs,
     the cooldown is cleared immediately without waiting for clock expiry.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.indicators import atr, ema_last, ema_series, wick_stats
from core.market_data import Bars

if TYPE_CHECKING:
    from agents.state import SharedState

log = logging.getLogger("core.wave_engine")

CAPACITY_HEALTHY = "HEALTHY"
CAPACITY_MATURE = "MATURE"
CAPACITY_EXHAUSTED = "EXHAUSTED"


@dataclass(frozen=True)
class WaveCapacity:
    capacity: str            # HEALTHY | MATURE | EXHAUSTED
    direction: str           # BUY | SELL | NONE
    chain_count: int         # Trades taken in this wave
    extension_atr: float     # Current extension measured in ATR M5
    is_exhausted: bool       # True if trend capacity is spent
    can_chain: bool          # True if next continuation entry is permitted
    size_multiplier: float   # 1.0 for healthy, 0.75 for mature, 0.0 for exhausted
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "capacity": self.capacity,
            "direction": self.direction,
            "chain_count": self.chain_count,
            "extension_atr": round(self.extension_atr, 2),
            "is_exhausted": self.is_exhausted,
            "can_chain": self.can_chain,
            "size_multiplier": round(self.size_multiplier, 2),
            "reason": self.reason,
        }


class DataDrivenWaveEngine:
    """Manages wave tracking, capacity projection, and smart broken wave invalidation."""

    def __init__(
        self,
        broken_wave_cooldown_s: int = 90,
        idle_reset_s: int = 150,
    ) -> None:
        self.broken_wave_cooldown_s = broken_wave_cooldown_s
        self.idle_reset_s = idle_reset_s

        self.current_direction: str | None = None
        self.origin_price: float | None = None
        self.chain_count: int = 0
        self.last_trade_time: float = 0.0
        self.broken_cooldown_until: float = 0.0
        self.broken_direction: str | None = None

    def record_trade_opened(
        self,
        direction: str,
        price: float,
        timestamp: float | None = None,
    ) -> None:
        """Record a new wave continuation trade."""
        now = timestamp if timestamp is not None else time.time()
        dir_norm = direction.upper()

        # If direction flipped or idle reset exceeded, start new wave
        if self.current_direction != dir_norm or (now - self.last_trade_time > self.idle_reset_s):
            self.current_direction = dir_norm
            self.origin_price = price
            self.chain_count = 1
        else:
            self.chain_count += 1

        self.last_trade_time = now
        log.info(
            "WAVE ENGINE: Trade #%d opened in %s wave @ %.2f (origin: %.2f)",
            self.chain_count,
            dir_norm,
            price,
            self.origin_price or price,
        )

    def record_trade_closed(
        self,
        is_win: bool,
        direction: str,
        timestamp: float | None = None,
        cooldown_seconds: int | None = None,
    ) -> None:
        """Record trade completion and manage broken wave invalidation."""
        now = timestamp if timestamp is not None else time.time()
        self.last_trade_time = now
        dir_norm = direction.upper()

        if is_win:
            log.info("WAVE ENGINE: Trade in %s wave won (Chain #%d). Wave intact.", dir_norm, self.chain_count)
        else:
            cd_s = cooldown_seconds if cooldown_seconds is not None else self.broken_wave_cooldown_s
            cd_s = max(self.broken_wave_cooldown_s, cd_s)
            self.broken_direction = dir_norm
            self.broken_cooldown_until = now + cd_s
            self.current_direction = None
            self.origin_price = None
            self.chain_count = 0
            log.warning(
                "WAVE ENGINE: Gelombang %s patah (cutloss)! Mengaktifkan Smart Cooldown %ds (sampai +%ds) khusus arah %s.",
                dir_norm,
                cd_s,
                cd_s,
                dir_norm,
            )

    def is_in_broken_cooldown(
        self,
        direction: str,
        timestamp: float | None = None,
    ) -> tuple[bool, int]:
        """Check if requested direction is locked by a recent broken wave."""
        now = timestamp if timestamp is not None else time.time()
        dir_norm = direction.upper()
        if now < self.broken_cooldown_until and self.broken_direction == dir_norm:
            rem = max(0, int(self.broken_cooldown_until - now))
            return True, rem
        return False, 0

    def clear_broken_cooldown(self, reason: str = "structure_reset") -> None:
        """Clear broken wave cooldown early when new valid structure confirms."""
        if self.broken_cooldown_until > 0.0:
            log.info("WAVE ENGINE: Early release broken-wave cooldown cleared (reason: %s)", reason)
        self.broken_cooldown_until = 0.0
        self.broken_direction = None

    def evaluate_wave(
        self,
        state: SharedState,
        candidate_direction: str,
        current_price: float | None = None,
        timestamp: float | None = None,
    ) -> WaveCapacity:
        """Evaluate real-time capacity and projection of the candidate wave based on market data."""
        dir_norm = candidate_direction.upper()
        now = timestamp if timestamp is not None else time.time()

        # 1. Check Broken Wave Cooldown
        in_broken_cd, rem_cd = self.is_in_broken_cooldown(dir_norm, now)
        if in_broken_cd:
            return WaveCapacity(
                capacity=CAPACITY_EXHAUSTED,
                direction=dir_norm,
                chain_count=self.chain_count,
                extension_atr=0.0,
                is_exhausted=True,
                can_chain=False,
                size_multiplier=0.0,
                reason=f"Broken wave cooldown active ({rem_cd}s remaining for {dir_norm})",
            )

        b_m5 = Bars.for_timeframe(state, "M5")
        b_m1 = Bars.for_timeframe(state, "M1")
        if b_m5.n < 15 or b_m1.n < 10:
            return WaveCapacity(
                capacity=CAPACITY_HEALTHY,
                direction=dir_norm,
                chain_count=self.chain_count,
                extension_atr=1.0,
                is_exhausted=False,
                can_chain=True,
                size_multiplier=1.0,
                reason="Insufficient history, default healthy capacity",
            )

        price = current_price or b_m1.last_close
        atr_m5 = max(0.60, atr(b_m5.highs, b_m5.lows, b_m5.closes, 14))

        # 2. Compute Wave Extension Distance
        ema9 = ema_last(b_m5.closes, 9)
        if self.current_direction == dir_norm and self.origin_price is not None:
            dist = abs(price - self.origin_price)
        else:
            dist = abs(price - ema9)

        extension_atr = dist / atr_m5

        # 3. Check Candle Structure Rejection / Degradation
        # Last M1 closed bar
        bar_idx = -2 if b_m1.n >= 3 else -1
        u_wick, l_wick, _ = wick_stats(
            b_m1.opens[bar_idx], b_m1.highs[bar_idx], b_m1.lows[bar_idx], b_m1.closes[bar_idx]
        )
        c_range = max(0.05, b_m1.highs[bar_idx] - b_m1.lows[bar_idx])
        has_counter_wick = (
            (dir_norm == "SELL" and (l_wick / c_range) >= 0.40)
            or (dir_norm == "BUY" and (u_wick / c_range) >= 0.40)
        )

        # 3b. Counter-Trend Awareness & Single-Shot Restriction:
        # If wave direction opposes Higher Timeframe trend (e.g. BUY during session waterfall drop / bear trend),
        # pullback bounces are strictly SINGLE-SHOT! Wave chaining (Trade #2, #3...) is disabled.
        is_counter_trend = False
        if state is not None and hasattr(state, "extra") and isinstance(state.extra, dict):
            regime = str(state.extra.get("market_regime", "")).upper()
            if dir_norm == "BUY" and (state.extra.get("session_waterfall_bear") or "BEAR" in regime):
                is_counter_trend = True
            elif dir_norm == "SELL" and (state.extra.get("session_waterfall_bull") or "BULL" in regime):
                is_counter_trend = True

        b_m15 = Bars.for_timeframe(state, "M15") if state else None
        if b_m15 and b_m15.n >= 15:
            ema20_m15 = ema_last(b_m15.closes, min(20, b_m15.n))
            ema50_m15 = ema_last(b_m15.closes, min(50, b_m15.n))
            if dir_norm == "BUY" and ema20_m15 < ema50_m15:
                is_counter_trend = True
            elif dir_norm == "SELL" and ema20_m15 > ema50_m15:
                is_counter_trend = True

        if is_counter_trend and self.chain_count >= 1:
            return WaveCapacity(
                capacity=CAPACITY_EXHAUSTED,
                direction=dir_norm,
                chain_count=self.chain_count,
                extension_atr=extension_atr,
                is_exhausted=True,
                can_chain=False,
                size_multiplier=0.0,
                reason=f"Counter-trend wave is single-shot only (Chain #{self.chain_count} finished, HTF opposing)",
            )

        # 4. Data-Driven Classification
        if extension_atr > 2.50 or (extension_atr > 2.0 and has_counter_wick):
            return WaveCapacity(
                capacity=CAPACITY_EXHAUSTED,
                direction=dir_norm,
                chain_count=self.chain_count,
                extension_atr=extension_atr,
                is_exhausted=True,
                can_chain=False,
                size_multiplier=0.0,
                reason=f"Wave exhausted by data projection ({extension_atr:.1f}x ATR from base)",
            )

        if extension_atr > 1.80:
            return WaveCapacity(
                capacity=CAPACITY_MATURE,
                direction=dir_norm,
                chain_count=self.chain_count,
                extension_atr=extension_atr,
                is_exhausted=False,
                can_chain=True,
                size_multiplier=0.75,
                reason=f"Mature wave ({extension_atr:.1f}x ATR), continuing with protective 0.75x sizing",
            )

        return WaveCapacity(
            capacity=CAPACITY_HEALTHY,
            direction=dir_norm,
            chain_count=self.chain_count,
            extension_atr=extension_atr,
            is_exhausted=False,
            can_chain=True,
            size_multiplier=1.0,
            reason=f"Healthy wave ({extension_atr:.1f}x ATR), rapid impulse chaining permitted",
        )
