"""Tests for the market session clock (Phase 2.7)."""

from datetime import UTC, datetime

from core.clock import KILLZONES, SESSIONS, MarketClock, Window


def _dt(hour: int, minute: int = 0, weekday_offset: int = 0) -> datetime:
    # 2026-01-07 is a Wednesday
    base = datetime(2026, 1, 7, hour, minute, tzinfo=UTC)
    return base


def test_window_wrap_around() -> None:
    w = Window(start=datetime(2026, 1, 1, 21, 0).time(), end=datetime(2026, 1, 1, 6, 0).time())
    assert w.contains(datetime(2026, 1, 1, 23, 0).time())
    assert w.contains(datetime(2026, 1, 1, 2, 0).time())
    assert not w.contains(datetime(2026, 1, 1, 12, 0).time())


def test_sessions_at_london_overlap() -> None:
    clock = MarketClock()
    active = clock.sessions_at(_dt(13, 0))
    assert "london" in active
    assert "newyork" in active
    assert "tokyo" not in active


def test_primary_session_prefers_london_then_ny() -> None:
    clock = MarketClock()
    assert clock.primary_session(_dt(13, 0)) == "london"
    assert clock.primary_session(_dt(17, 0)) == "newyork"
    assert clock.primary_session(_dt(2, 0)) == "tokyo"


def test_killzones() -> None:
    clock = MarketClock()
    assert clock.is_killzone(_dt(8, 0), "london_open")
    assert clock.current_killzone(_dt(8, 0)) == "london_open"
    assert clock.current_killzone(_dt(11, 0)) is None
    assert clock.is_killzone(_dt(13, 0))  # ny_open / overlap


def test_market_open_weekend() -> None:
    clock = MarketClock()
    assert clock.is_market_open(datetime(2026, 1, 7, 10, 0, tzinfo=UTC))  # Wed
    assert not clock.is_market_open(datetime(2026, 1, 10, 10, 0, tzinfo=UTC))  # Sat
    assert not clock.is_market_open(datetime(2026, 1, 11, 12, 0, tzinfo=UTC))  # Sun 12:00
    assert clock.is_market_open(datetime(2026, 1, 11, 23, 0, tzinfo=UTC))  # Sun 23:00
    assert not clock.is_market_open(datetime(2026, 1, 9, 22, 0, tzinfo=UTC))  # Fri 22:00


def test_low_liquidity() -> None:
    clock = MarketClock()
    assert clock.is_low_liquidity(_dt(3, 0))  # asia, no killzone
    assert not clock.is_low_liquidity(_dt(13, 0))  # london/ny


def test_describe_shape() -> None:
    clock = MarketClock()
    info = clock.describe(_dt(13, 0))
    assert info["primary_session"] == "london"
    assert info["market_open"] is True
    assert set(SESSIONS) <= {"sydney", "tokyo", "london", "newyork"}
    assert "london_open" in KILLZONES


def test_london_open_freeze() -> None:
    clock = MarketClock()
    # 08:00 to 08:14 UTC should be freeze
    assert clock.is_london_open_freeze(_dt(8, 0)) is True
    assert clock.is_london_open_freeze(_dt(8, 14)) is True
    # 08:15 and later should NOT be freeze
    assert clock.is_london_open_freeze(_dt(8, 15)) is False
    assert clock.is_london_open_freeze(_dt(7, 59)) is False
    assert clock.is_london_open_freeze(_dt(9, 0)) is False


def test_session_hard_cutoff() -> None:
    clock = MarketClock()
    # 15:30 UTC or later should be cutoff
    assert clock.is_hard_cutoff(_dt(15, 29)) is False
    assert clock.is_hard_cutoff(_dt(15, 30)) is True
    assert clock.is_hard_cutoff(_dt(16, 0)) is True
    assert clock.is_hard_cutoff(_dt(22, 0)) is True
    assert clock.is_hard_cutoff(_dt(10, 0)) is False
