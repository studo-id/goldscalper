"""Cross-asset correlation service: Synthetic DXY & Silver (XAGUSD).

Polls FX majors (EURUSD, USDJPY, GBPUSD) and Silver (XAGUSD) from the MT5 bridge
to provide real-time Dollar Index (DXY) momentum and precious metal cross-asset
correlation for Gold (XAUUSD).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from agents.divisions.timeframe.dxy import calculate_synthetic_dxy
from config.logging import get_logger
from core.mt5_connector import MT5Client

UTC = timezone.utc
log = get_logger("core.cross_asset")


class CrossAssetService:
    """Tracks FX majors and precious metals to feed synthetic DXY and correlation agents."""

    def __init__(
        self,
        client: MT5Client,
        symbol_suffix: str = "m",
        poll_interval_s: float = 3.0,
    ) -> None:
        self.client = client
        self.suffix = symbol_suffix
        self.poll_interval_s = poll_interval_s

        self.sym_eurusd = f"EURUSD{symbol_suffix}"
        self.sym_usdjpy = f"USDJPY{symbol_suffix}"
        self.sym_gbpusd = f"GBPUSD{symbol_suffix}"
        self.sym_silver = f"XAGUSD{symbol_suffix}"

        # Current quotes
        self._eurusd: float | None = None
        self._usdjpy: float | None = None
        self._gbpusd: float | None = None
        self._silver: float | None = None

        # DXY & Baselines
        self._dxy: float | None = None
        self._dxy_baseline: float | None = None
        self._silver_baseline: float | None = None

        # Timestamps & session tracking
        self._last_poll: datetime | None = None
        self._current_session: str | None = None
        self._lock = asyncio.Lock()

    async def update(self, current_session: str | None = None) -> dict[str, Any]:
        """Poll latest quotes if interval has elapsed and return cross-asset state dictionary."""
        now = datetime.now(UTC)

        # Reset baselines at session transition
        if current_session and current_session != self._current_session:
            self._current_session = current_session
            self._dxy_baseline = self._dxy
            self._silver_baseline = self._silver
            log.info("session changed to %s; anchored cross-asset baselines (DXY=%s, XAG=%s)",
                     current_session, self._dxy_baseline, self._silver_baseline)

        # Rate-limiting check
        if self._last_poll and (now - self._last_poll).total_seconds() < self.poll_interval_s:
            return self.get_extra_state()

        async with self._lock:
            # Poll FX majors and Silver concurrently
            results = await asyncio.gather(
                self._safe_tick(self.sym_eurusd),
                self._safe_tick(self.sym_usdjpy),
                self._safe_tick(self.sym_gbpusd),
                self._safe_tick(self.sym_silver),
                return_exceptions=True,
            )

            eur, jpy, gbp, sil = results

            if isinstance(eur, float) and eur > 0:
                self._eurusd = eur
            if isinstance(jpy, float) and jpy > 0:
                self._usdjpy = jpy
            if isinstance(gbp, float) and gbp > 0:
                self._gbpusd = gbp
            if isinstance(sil, float) and sil > 0:
                self._silver = sil

            # Update synthetic DXY if all 3 majors are available
            if self._eurusd and self._usdjpy and self._gbpusd:
                new_dxy = calculate_synthetic_dxy(self._eurusd, self._usdjpy, self._gbpusd)
                self._dxy = new_dxy

                if self._dxy_baseline is None:
                    self._dxy_baseline = new_dxy

            if self._silver and self._silver_baseline is None:
                self._silver_baseline = self._silver

            self._last_poll = now

        return self.get_extra_state()

    async def _safe_tick(self, symbol: str) -> float | None:
        try:
            quote = await self.client.symbol_tick(symbol)
            if quote and quote.bid > 0:
                return float(quote.bid)
        except Exception as exc:
            log.debug("failed to fetch tick for %s: %s", symbol, exc)
        return None

    def get_extra_state(self) -> dict[str, Any]:
        """Produce dictionary payload ready for injection into SharedState.extra."""
        dxy_delta = None
        if self._dxy is not None and self._dxy_baseline is not None:
            dxy_delta = round(self._dxy - self._dxy_baseline, 2)

        silver_delta = None
        if self._silver is not None and self._silver_baseline is not None:
            silver_delta = round(self._silver - self._silver_baseline, 3)

        return {
            "eurusd": self._eurusd,
            "usdjpy": self._usdjpy,
            "gbpusd": self._gbpusd,
            "silver": self._silver,
            "dxy": self._dxy,
            "dxy_baseline": self._dxy_baseline,
            "dxy_delta": dxy_delta,
            "silver_baseline": self._silver_baseline,
            "silver_delta": silver_delta,
        }
