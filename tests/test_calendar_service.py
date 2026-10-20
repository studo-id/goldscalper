"""Unit tests for EconomicCalendarService currency filtering and blackout logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.calendar_service import EconomicCalendarService, EconomicEvent

UTC = timezone.utc


def test_blackout_ignores_non_usd_events() -> None:
    svc = EconomicCalendarService(cache_path=Path("tmp_cache.json"))
    now = datetime(2026, 10, 20, 5, 55, tzinfo=UTC)

    # UK news at 06:00 UTC (in 5 minutes)
    uk_event = EconomicEvent(
        title="UK Labour Market Report October 2026",
        country="GLOBAL",
        time=datetime(2026, 10, 20, 6, 0, tzinfo=UTC),
        impact="High",
    )
    svc._events = [uk_event]

    # Default check_blackout targets USD/US -> must NOT trigger blackout
    blackout, detail = svc.check_blackout(now)
    assert blackout is False
    assert detail is None


def test_blackout_triggers_on_usd_events() -> None:
    svc = EconomicCalendarService(cache_path=Path("tmp_cache.json"))
    now = datetime(2026, 10, 20, 12, 10, tzinfo=UTC)

    # US CPI news at 12:30 UTC (in 20 minutes)
    us_event = EconomicEvent(
        title="US CPI Inflation Rate",
        country="USD",
        time=datetime(2026, 10, 20, 12, 30, tzinfo=UTC),
        impact="High",
    )
    svc._events = [us_event]

    # Must trigger blackout
    blackout, detail = svc.check_blackout(now)
    assert blackout is True
    assert detail is not None
    assert detail["country"] == "USD"
    assert detail["phase"] == "BEFORE"
