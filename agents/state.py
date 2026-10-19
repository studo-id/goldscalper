"""Shared market/agent state passed to every agent per cycle.

Kept dependency-light (no pandas) so the framework is testable in isolation.
Market data is exposed as opaque frames/indicators that data agents populate in
later phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

# Vote values
VOTE_SELL = -1
VOTE_NEUTRAL = 0
VOTE_BUY = 1

# Veto flags
VETO_BUY = "VETO_BUY"
VETO_SELL = "VETO_SELL"
VETO_ALL = "VETO_ALL"


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(UTC)


@dataclass
class SharedState:
    """Immutable-ish snapshot of the world for one decision cycle."""

    symbol: str = "XAUUSD"
    ts: datetime = field(default_factory=utcnow)

    # Latest quote
    bid: float | None = None
    ask: float | None = None
    spread_points: float | None = None

    # Session context (e.g. "london", "newyork", "asia", "closed")
    session: str = "unknown"

    # Market data populated by data agents (Phase 2): timeframe -> frame/rows
    frames: dict[str, Any] = field(default_factory=dict)
    # Precomputed indicators shared across agents: key -> value
    indicators: dict[str, Any] = field(default_factory=dict)

    # Open positions snapshot (list of dicts)
    positions: list[dict[str, Any]] = field(default_factory=list)

    # Risk/account context
    equity: float | None = None
    balance: float | None = None
    daily_pnl_pct: float = 0.0
    weekly_pnl_pct: float = 0.0
    consecutive_losses: int = 0
    daily_loss_exceeded: bool = False
    weekly_loss_exceeded: bool = False

    # Juggler & BizDev context
    daily_realized_pnl: float = 0.0
    balance_start_of_day: float | None = None
    daily_profit_locked: bool = False
    daily_gross_profit: float = 0.0
    daily_friction_cost: float = 0.0
    daily_lots_traded: float = 0.0

    # Free-form extras (news flags, regime, etc.)
    extra: dict[str, Any] = field(default_factory=dict)

    # --- Helpers ---------------------------------------------------------------
    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2.0
        return self.bid or self.ask

    def last_price(self) -> float | None:
        return self.mid

    def flag(self, key: str, default: Any = None) -> Any:
        return self.extra.get(key, default)

    def is_news_blackout(self) -> bool:
        return bool(self.extra.get("news_blackout", False))

    def is_low_liquidity(self) -> bool:
        return self.session in {"asia", "closed"} or bool(
            self.extra.get("low_liquidity", False)
        )
