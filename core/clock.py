"""Market session clock: sessions and killzones in UTC.

Gold (XAUUSD) trades ~23h/day through the Sydney→Tokyo→London→New York cycle,
closing on weekends. Sessions may overlap (London/NY). Killzones are the
high-probability windows where scalpers prefer to enter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc  # Python 3.10 compat


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(frozen=True)
class Window:
    """A daily time window in UTC; supports wrap-around (e.g. 21:00→06:00)."""

    start: time
    end: time

    def contains(self, t: time) -> bool:
        if self.start <= self.end:
            return self.start <= t < self.end
        # wraps midnight
        return t >= self.start or t < self.end


# Coarse session windows (UTC)
SESSIONS: dict[str, Window] = {
    "sydney": Window(time(21, 0), time(6, 0)),
    "tokyo": Window(time(0, 0), time(9, 0)),
    "london": Window(time(7, 0), time(16, 0)),
    "newyork": Window(time(12, 0), time(21, 0)),
}

# Higher-probability entry windows (UTC)
KILLZONES: dict[str, Window] = {
    "london_open": Window(time(7, 0), time(10, 0)),
    "ny_open": Window(time(12, 0), time(15, 0)),
    "london_ny_overlap": Window(time(12, 0), time(16, 0)),
    "asian_range": Window(time(0, 0), time(3, 0)),
    "ny_close": Window(time(19, 0), time(21, 0)),
}


class MarketClock:
    """Query session/killzone context for a given instant."""

    def __init__(
        self,
        sessions: dict[str, Window] | None = None,
        killzones: dict[str, Window] | None = None,
    ) -> None:
        self.sessions = sessions or SESSIONS
        self.killzones = killzones or KILLZONES

    def sessions_at(self, dt: datetime) -> list[str]:
        t = _to_utc(dt).time()
        return [name for name, w in self.sessions.items() if w.contains(t)]

    def primary_session(self, dt: datetime) -> str:
        """Best-guess single session label (prefers london/newyork on overlap)."""
        active = self.sessions_at(dt)
        for preferred in ("london", "newyork", "tokyo", "sydney"):
            if preferred in active:
                return preferred
        return "closed"

    def current_killzone(self, dt: datetime) -> str | None:
        t = _to_utc(dt).time()
        for name, w in self.killzones.items():
            if w.contains(t):
                return name
        return None

    def is_killzone(self, dt: datetime, name: str | None = None) -> bool:
        if name is None:
            return self.current_killzone(dt) is not None
        return self.killzones[name].contains(_to_utc(dt).time())

    def is_market_open(self, dt: datetime) -> bool:
        """Open if any session is active; markets close most of the weekend."""
        d = _to_utc(dt)
        # Conservative weekend close: Saturday all day, Sunday before 22:00.
        if d.weekday() == 5:
            return False
        if d.weekday() == 6 and d.hour < 22:
            return False
        if d.weekday() == 4 and d.hour >= 21:  # Friday after 21:00 UTC
            return False
        return True

    def is_low_liquidity(self, dt: datetime) -> bool:
        """Thin hours: only sydney/tokyo active and outside killzones."""
        active = set(self.sessions_at(dt))
        if active & {"london", "newyork"}:
            return False
        return self.current_killzone(dt) is None

    def is_london_open_freeze(self, dt: datetime) -> bool:
        """True during first 15 mins of London open (08:00 - 08:15 UTC)."""
        t = _to_utc(dt).time()
        return time(8, 0) <= t < time(8, 15)

    def is_hard_cutoff(self, dt: datetime) -> bool:
        """True after 15:30 UTC until 21:00 UTC (end of high-volume intraday trading)."""
        t = _to_utc(dt).time()
        return time(15, 30) <= t < time(21, 0)

    def is_overnight_flat_window(self, dt: datetime) -> bool:
        """True during daily rollover break or weekend close."""
        return is_overnight_flat_window(dt)

    def describe(self, dt: datetime) -> dict[str, object]:
        return {
            "ts": _to_utc(dt).isoformat(),
            "sessions": self.sessions_at(dt),
            "primary_session": self.primary_session(dt),
            "killzone": self.current_killzone(dt),
            "market_open": self.is_market_open(dt),
            "low_liquidity": self.is_low_liquidity(dt),
            "london_open_freeze": self.is_london_open_freeze(dt),
            "hard_cutoff": self.is_hard_cutoff(dt),
            "overnight_flat_window": self.is_overnight_flat_window(dt),
        }


def is_overnight_flat_window(dt: datetime) -> bool:
    """True during daily rollover break or weekend close when intraday positions must be flat.

    Rollover/flat cutoff rules for Gold (XAUUSD):
    1. Weekend gap risk: Friday 20:50 UTC onwards through Sunday 22:00 UTC market open.
    2. Mon-Thu daily rollover break: 20:50 UTC to 22:00 UTC (spread explosion / daily settlement break).
    Once 22:00 UTC arrives on Sun-Thu, market is active for Asia session (NOT cutoff).
    """
    d = _to_utc(dt)
    w = d.weekday()
    h = d.hour
    m = d.minute

    # Friday close into weekend: Friday >= 20:50 UTC through Sunday < 22:00 UTC
    if w == 4 and (h > 20 or (h == 20 and m >= 50)):
        return True
    if w == 5:  # Saturday
        return True
    if w == 6 and h < 22:  # Sunday before 22:00 UTC
        return True

    # Mon-Thu daily rollover break: between 20:50 and 22:00 UTC
    if w in (0, 1, 2, 3) and (h == 21 or (h == 20 and m >= 50)):
        return True

    return False
