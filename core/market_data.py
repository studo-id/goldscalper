"""Market data primitives: ticks, candles, aggregation, and an in-memory cache.

Deliberately pandas-free so it can be unit-tested and run inside the agent hot
path cheaply. Higher layers (agents) read candles from :class:`MarketDataCache`.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

# Timeframe -> seconds
TIMEFRAME_SECONDS: dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

# Ordered fast -> slow
TIMEFRAMES: list[str] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]


def tf_seconds(timeframe: str) -> int:
    """Seconds in one bar of ``timeframe`` (e.g. 'M5' -> 300)."""
    try:
        return TIMEFRAME_SECONDS[timeframe.upper()]
    except KeyError as exc:  # pragma: no cover - guarded by callers
        raise ValueError(f"unknown timeframe: {timeframe}") from exc


def bucket_start(ts: datetime, timeframe: str) -> datetime:
    """Floor ``ts`` to the start of its bar for ``timeframe`` (UTC)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    ts = ts.astimezone(UTC)
    secs = tf_seconds(timeframe)
    epoch = int(ts.timestamp())
    floored = epoch - (epoch % secs)
    return datetime.fromtimestamp(floored, tz=UTC)


@dataclass(slots=True)
class Tick:
    symbol: str
    time: datetime
    bid: float
    ask: float
    volume: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return max(0.0, self.ask - self.bid)


@dataclass(slots=True)
class Candle:
    symbol: str
    timeframe: str
    time: datetime  # bar open time (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    spread_avg: float = 0.0
    ticks: int = 0  # number of ticks aggregated (not persisted)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "time": self.time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "spread_avg": self.spread_avg,
        }


@dataclass
class TimeframeAggregator:
    """Aggregate ticks into OHLCV candles for one (symbol, timeframe)."""

    symbol: str
    timeframe: str
    _current: Candle | None = None
    _spread_sum: float = 0.0
    _spread_n: int = 0

    def add_tick(self, tick: Tick) -> Candle | None:
        """Feed a tick; return the just-closed candle if a new bar started."""
        price = tick.mid
        bar_time = bucket_start(tick.time, self.timeframe)
        closed: Candle | None = None

        if self._current is None:
            self._current = Candle(
                symbol=self.symbol,
                timeframe=self.timeframe,
                time=bar_time,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=tick.volume,
                ticks=1,
            )
            self._spread_sum = tick.spread
            self._spread_n = 1
            return None

        if bar_time > self._current.time:
            closed = self._finalize()
            self._current = Candle(
                symbol=self.symbol,
                timeframe=self.timeframe,
                time=bar_time,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=tick.volume,
                ticks=1,
            )
            self._spread_sum = tick.spread
            self._spread_n = 1
            return closed

        # Same bar: update OHLCV
        cur = self._current
        cur.high = max(cur.high, price)
        cur.low = min(cur.low, price)
        cur.close = price
        cur.volume += tick.volume
        cur.ticks += 1
        self._spread_sum += tick.spread
        self._spread_n += 1
        return None

    def _finalize(self) -> Candle:
        cur = self._current
        assert cur is not None
        cur.spread_avg = (self._spread_sum / self._spread_n) if self._spread_n else 0.0
        return cur

    def flush(self) -> Candle | None:
        """Return the current (possibly incomplete) candle."""
        if self._current is None:
            return None
        return self._finalize()

    @property
    def current(self) -> Candle | None:
        return self._current


class MarketDataCache:
    """Bounded in-memory store of recent candles keyed by (symbol, timeframe)."""

    def __init__(self, maxlen: int = 1000) -> None:
        self.maxlen = maxlen
        self._data: dict[tuple[str, str], deque[Candle]] = {}

    def append(self, candle: Candle) -> None:
        key = (candle.symbol, candle.timeframe)
        buf = self._data.get(key)
        if buf is None:
            buf = deque(maxlen=self.maxlen)
            self._data[key] = buf
        if buf and buf[-1].time == candle.time:
            buf[-1] = candle  # replace same-bar update
        else:
            buf.append(candle)

    def latest(self, symbol: str, timeframe: str, n: int = 1) -> list[Candle]:
        buf = self._data.get((symbol, timeframe))
        if not buf:
            return []
        n = max(1, n)
        return list(buf)[-n:]

    def closed(self, symbol: str, timeframe: str, n: int = 1) -> list[Candle]:
        """Return last ``n`` candles assuming the final one may be forming.

        Callers wanting strictly closed bars should pass the buffer minus the
        live bar; we simply return the last ``n`` for now (Phase 2 keeps it
        simple — the live bar is replaced in place as ticks arrive).
        """
        return self.latest(symbol, timeframe, n)

    def last_price(self, symbol: str) -> float | None:
        for tf in TIMEFRAMES:
            rows = self.latest(symbol, tf, 1)
            if rows:
                return rows[-1].close
        return None

    def to_frames(self, symbol: str) -> dict[str, list[dict[str, Any]]]:
        """Serialisable snapshot for agents / API."""
        return {
            tf: [c.as_dict() for c in self.latest(symbol, tf)]
            for tf in TIMEFRAMES
            if self._data.get((symbol, tf))
        }


def resample_ticks(ticks: Iterable[Tick], symbol: str, timeframe: str) -> list[Candle]:
    """Convenience: aggregate an iterable of ticks into closed candles."""
    agg = TimeframeAggregator(symbol, timeframe)
    out: list[Candle] = []
    for tick in ticks:
        closed = agg.add_tick(tick)
        if closed is not None:
            out.append(closed)
    final = agg.flush()
    if final is not None:
        out.append(final)
    return out


def expected_bars(start: datetime, end: datetime, timeframe: str) -> int:
    """Number of bars expected between two instants (for gap detection)."""
    secs = tf_seconds(timeframe)
    return max(0, int((end - start).total_seconds() // secs))


def find_gaps(candles: list[Candle], timeframe: str) -> list[tuple[datetime, datetime]]:
    """Return (gap_start, gap_end) pairs where bars are missing.

    Weekends (market close Fri 21:00 UTC → Sun 22:00 UTC) are not treated as
    gaps, since gold is closed then.
    """
    gaps: list[tuple[datetime, datetime]] = []
    step = timedelta(seconds=tf_seconds(timeframe))
    for prev, nxt in zip(candles, candles[1:], strict=False):
        if nxt.time - prev.time > step:
            gap_start = prev.time + step
            if _is_market_closed(gap_start, nxt.time):
                continue
            gaps.append((gap_start, nxt.time))
    return gaps


def _is_market_closed(start: datetime, end: datetime) -> bool:
    """Heuristic: a gap is 'closed' if it spans a weekend window."""
    if (end - start).total_seconds() < 24 * 3600:
        return False
    # If the gap contains a Saturday, treat as weekend closure.
    day = start
    while day < end:
        if day.weekday() == 5:  # Saturday
            return True
        day += timedelta(days=1)
    return False


@dataclass
class CandleSeries:
    """Optional helper wrapper to query a series with a symbol/timeframe label."""

    symbol: str
    timeframe: str
    candles: list[Candle] = field(default_factory=list)

    def closes(self) -> list[float]:
        return [c.close for c in self.candles]


@dataclass(slots=True)
class Bars:
    """Columnar OHLC view extracted from a frame.

    Accepts :class:`Candle` objects, plain dicts, or any object exposing
    ``open``/``high``/``low``/``close`` attributes. Shared by the timeframe and
    risk divisions (and any later agent that needs OHLC without pandas).
    """

    opens: list[float] = field(default_factory=list)
    highs: list[float] = field(default_factory=list)
    lows: list[float] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)
    volumes: list[float] = field(default_factory=list)
    times: list[Any] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.closes)

    @property
    def last_close(self) -> float:
        return self.closes[-1] if self.closes else 0.0

    def slope(self, k: int = 2) -> float:
        """Net change across the last ``k`` bars (close[-1] - close[-1-k])."""
        if self.n <= k:
            return 0.0
        return self.closes[-1] - self.closes[-1 - k]

    @classmethod
    def from_rows(cls, rows: Any) -> Bars:
        bars = cls()
        if not rows:
            return bars
        for row in rows:
            if isinstance(row, Candle):
                o, h, low, c = row.open, row.high, row.low, row.close
                vol = row.volume
                t = row.time
            elif isinstance(row, dict):
                o, h, low, c = row["open"], row["high"], row["low"], row["close"]
                vol = row.get("volume", 0.0)
                t = row.get("time")
            else:
                o, h, low, c = row.open, row.high, row.low, row.close
                vol = getattr(row, "volume", 0.0)
                t = getattr(row, "time", None)
            bars.opens.append(float(o))
            bars.highs.append(float(h))
            bars.lows.append(float(low))
            bars.closes.append(float(c))
            bars.volumes.append(float(vol or 0.0))
            bars.times.append(t)
        return bars

    @classmethod
    def for_timeframe(cls, state: Any, timeframe: str) -> Bars:
        """Convenience: extract a timeframe's rows from a ``SharedState.frames``."""
        if not timeframe:
            return cls()
        frames = getattr(state, "frames", {}) or {}
        rows = frames.get(timeframe)
        if rows is None:
            rows = frames.get(timeframe.upper())
        return cls.from_rows(rows or [])
