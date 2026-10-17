"""Pure-Python technical indicators (pandas-free).

Small, dependency-free helpers shared by the timeframe/technical divisions.
Every function operates on plain float sequences so agents stay cheap and
unit-testable; callers build these sequences from
:class:`core.market_data.Candle` rows.
"""

from __future__ import annotations

from collections.abc import Sequence


def ema_series(values: Sequence[float], period: int) -> list[float]:
    """Exponential moving average with ``adjust=False`` semantics."""
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[float] = []
    k = 2.0 / (period + 1.0)
    prev: float | None = None
    for value in values:
        fv = float(value)
        prev = fv if prev is None else (fv * k) + (prev * (1.0 - k))
        out.append(prev)
    return out


def ema_last(values: Sequence[float], period: int, default: float = 0.0) -> float:
    """Last value of the EMA series, or ``default`` when there is no data."""
    if not values:
        return default
    return ema_series(values, period)[-1]


def true_ranges(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> list[float]:
    """Per-bar True Range (first bar uses high-low)."""
    out: list[float] = []
    prev_close: float | None = None
    for high, low, close in zip(highs, lows, closes, strict=False):
        h, low_, c = float(high), float(low), float(close)
        if prev_close is None:
            out.append(h - low_)
        else:
            out.append(max(h - low_, abs(h - prev_close), abs(low_ - prev_close)))
        prev_close = c
    return out


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
    default: float = 1.0,
) -> float:
    """Simple (mean-of-TR) Average True Range over the last ``period`` bars."""
    n = len(closes)
    if n < 2:
        return default
    trs = true_ranges(highs, lows, closes)
    window = trs[-min(period, n) :]
    return (sum(window) / len(window)) if window else default


def wick_stats(
    open_: float,
    high: float,
    low: float,
    close: float,
) -> tuple[float, float, float]:
    """Return (upper_wick, lower_wick, body) as ratios of the candle range."""
    o, h, low_, c = float(open_), float(high), float(low), float(close)
    rng = max(1e-9, h - low_)
    upper = (h - max(o, c)) / rng
    lower = (min(o, c) - low_) / rng
    body = abs(c - o) / rng
    return upper, lower, body


def mean(values: Sequence[float]) -> float:
    """Arithmetic mean; 0.0 for an empty sequence."""
    vals = list(values)
    return (sum(vals) / len(vals)) if vals else 0.0


def rsi_series(closes: Sequence[float], period: int = 14) -> list[float]:
    """Wilder's RSI series; empty when there is not enough data."""
    n = len(closes)
    if n <= period:
        return []
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, n):
        delta = float(closes[i]) - float(closes[i - 1])
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    def _rsi(avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out = [_rsi(avg_gain, avg_loss)]
    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
        out.append(_rsi(avg_gain, avg_loss))
    return out


def rsi_last(closes: Sequence[float], period: int = 14, default: float = 50.0) -> float:
    """Last RSI value, or ``default`` when there is not enough data."""
    series = rsi_series(closes, period)
    return series[-1] if series else default


def macd(
    closes: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[float, float, float]:
    """Return ``(macd_line, signal_line, histogram)`` last values."""
    if len(closes) < slow:
        return (0.0, 0.0, 0.0)
    fast_ema = ema_series(closes, fast)
    slow_ema = ema_series(closes, slow)
    line = [f - s for f, s in zip(fast_ema, slow_ema, strict=False)]
    signal = ema_series(line, signal_period)
    return (line[-1], signal[-1], line[-1] - signal[-1])


def bollinger(
    closes: Sequence[float],
    period: int = 20,
    mult: float = 2.0,
) -> tuple[float, float, float, float, float]:
    """Return ``(mid, upper, lower, pct_b, bandwidth)``.

    ``pct_b`` is the position of the last close within the bands (0 = lower,
    1 = upper); ``bandwidth`` is the band width normalised by the mid band.
    """
    if not closes:
        return (0.0, 0.0, 0.0, 0.5, 0.0)
    window = list(closes[-period:])
    mid = mean(window)
    if len(window) < 2:
        last = float(closes[-1])
        return (mid, last, last, 0.5, 0.0)
    variance = sum((x - mid) ** 2 for x in window) / len(window)
    sd = variance ** 0.5
    upper = mid + (mult * sd)
    lower = mid - (mult * sd)
    rng = max(1e-9, upper - lower)
    pct_b = (float(closes[-1]) - lower) / rng
    bandwidth = (upper - lower) / mid if mid else 0.0
    return (mid, upper, lower, pct_b, bandwidth)


def adx(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> tuple[float, float, float]:
    """Return ``(adx, plus_di, minus_di)`` using Wilder smoothing."""
    n = len(closes)
    if n < period + 1:
        return (0.0, 0.0, 0.0)

    plus_dm: list[float] = []
    minus_dm: list[float] = []
    trs: list[float] = []
    for i in range(1, n):
        up = float(highs[i]) - float(highs[i - 1])
        down = float(lows[i - 1]) - float(lows[i])
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        trs.append(
            max(
                float(highs[i]) - float(lows[i]),
                abs(float(highs[i]) - float(closes[i - 1])),
                abs(float(lows[i]) - float(closes[i - 1])),
            )
        )

    def _smooth(seq: list[float]) -> list[float]:
        acc = sum(seq[:period])
        out = [acc]
        for i in range(period, len(seq)):
            acc = acc - (acc / period) + seq[i]
            out.append(acc)
        return out

    smooth_tr = _smooth(trs)
    smooth_plus = _smooth(plus_dm)
    smooth_minus = _smooth(minus_dm)

    dxs: list[float] = []
    last_pdi = last_mdi = 0.0
    for i in range(len(smooth_tr)):
        tr_val = smooth_tr[i]
        if tr_val == 0:
            continue
        last_pdi = 100.0 * smooth_plus[i] / tr_val
        last_mdi = 100.0 * smooth_minus[i] / tr_val
        denom = last_pdi + last_mdi
        dxs.append(100.0 * abs(last_pdi - last_mdi) / denom if denom else 0.0)
    if not dxs:
        return (0.0, last_pdi, last_mdi)
    window = dxs[-min(period, len(dxs)) :]
    return (sum(window) / len(window), last_pdi, last_mdi)

