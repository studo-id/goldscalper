"""Economic calendar service and news blackout detector.

Pulls real-time macroeconomic event calendar (CPI, NFP, FOMC, Retail Sales, GDP),
provides local disk cache persistence to survive network downtime, and detects
pre/post event blackout windows for scalpers.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
import json
from pathlib import Path
from typing import Any

import httpx

from config.logging import get_logger

log = get_logger("core.calendar")

PRIMARY_FEED_URL = "https://www.financecalendar.com/wp-json/fc/v1/calendar?impact=high"
FALLBACK_FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_PATH = Path("data/calendar_cache.json")


@dataclass(slots=True)
class EconomicEvent:
    title: str
    country: str
    time: datetime
    impact: str  # "High" | "Medium" | "Low" | "Holiday"
    forecast: str = ""
    previous: str = ""

    @property
    def is_high_impact(self) -> bool:
        return self.impact.lower() == "high"


class EconomicCalendarService:
    """Manages economic calendar fetching, caching, and news blackout status."""

    def __init__(
        self,
        feed_url: str = PRIMARY_FEED_URL,
        fallback_url: str = FALLBACK_FEED_URL,
        refresh_interval_s: float = 3600.0,
        pre_news_minutes: int = 30,
        post_news_minutes: int = 20,
        cache_path: Path = CACHE_PATH,
    ) -> None:
        self.feed_url = feed_url
        self.fallback_url = fallback_url
        self.refresh_interval_s = refresh_interval_s
        self.retry_cooldown_s = 300.0  # 5 min cooldown on error to avoid rate limits
        self.pre_news_minutes = pre_news_minutes
        self.post_news_minutes = post_news_minutes
        self.cache_path = cache_path
        self._events: list[EconomicEvent] = []
        self._last_refresh: datetime | None = None
        self._last_attempt: datetime | None = None
        self._lock = asyncio.Lock()

        # Load from disk cache on initialization if available
        self._load_cache()

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
            events: list[EconomicEvent] = []
            for item in raw_list:
                dt = datetime.fromisoformat(item["time"]).astimezone(UTC)
                events.append(
                    EconomicEvent(
                        title=item["title"],
                        country=item.get("country", "USD"),
                        time=dt,
                        impact=item.get("impact", "High"),
                        forecast=item.get("forecast", ""),
                        previous=item.get("previous", ""),
                    )
                )
            self._events = events
            self._last_refresh = datetime.now(UTC)
            log.info("loaded %d cached economic events from %s", len(events), self.cache_path)
        except Exception as exc:
            log.warning("could not load calendar cache: %s", exc)

    def _save_cache(self, events: list[EconomicEvent]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            serializable = [
                {
                    "title": e.title,
                    "country": e.country,
                    "time": e.time.isoformat(),
                    "impact": e.impact,
                    "forecast": e.forecast,
                    "previous": e.previous,
                }
                for e in events
            ]
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=2)
        except Exception as exc:
            log.debug("could not save calendar cache: %s", exc)

    async def fetch_events(self) -> list[EconomicEvent]:
        """Fetch and parse calendar events from primary or fallback feed."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        }

        events: list[EconomicEvent] = []
        errors: list[str] = []

        # 1. Try Primary Feed (FinanceCalendar)
        try:
            async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
                resp = await client.get(self.feed_url)
                if resp.status_code == 200:
                    payload = resp.json()
                    raw_events = payload.get("events", []) if isinstance(payload, dict) else payload
                    for item in raw_events:
                        title = str(item.get("title") or item.get("name") or "").strip()
                        impact = str(item.get("impact", "high")).capitalize()
                        raw_dt = item.get("time_utc") or item.get("date")
                        if not raw_dt or not title:
                            continue
                        try:
                            event_dt = datetime.fromisoformat(str(raw_dt)).astimezone(UTC)
                        except Exception:
                            continue

                        # Determine if USD or Global
                        country = "USD" if any(k in title.upper() for k in ("US ", "USA", "FOMC", "FED", "PCE", "PAYROLL", "RETAIL SALES")) else "GLOBAL"

                        events.append(
                            EconomicEvent(
                                title=title,
                                country=country,
                                time=event_dt,
                                impact=impact,
                                forecast=str(item.get("consensus") or ""),
                                previous=str(item.get("prior") or ""),
                            )
                        )
        except Exception as exc:
            errors.append(f"primary: {exc}")

        # 2. Try Fallback if primary returned nothing
        if not events:
            try:
                async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
                    resp = await client.get(self.fallback_url)
                    if resp.status_code == 200:
                        data = resp.json()
                        for item in data:
                            country = str(item.get("country", "")).upper()
                            if country != "USD":
                                continue
                            impact = str(item.get("impact", "")).capitalize()
                            if impact not in ("High", "Medium"):
                                continue
                            raw_date = str(item.get("date", ""))
                            try:
                                event_dt = datetime.fromisoformat(raw_date).astimezone(UTC)
                            except Exception:
                                continue
                            events.append(
                                EconomicEvent(
                                    title=str(item.get("title", "")).strip(),
                                    country=country,
                                    time=event_dt,
                                    impact=impact,
                                    forecast=str(item.get("forecast", "")),
                                    previous=str(item.get("previous", "")),
                                )
                            )
            except Exception as exc:
                errors.append(f"fallback: {exc}")

        if not events and errors:
            raise RuntimeError(f"All calendar sources failed: {'; '.join(errors)}")

        events.sort(key=lambda e: e.time)
        async with self._lock:
            self._events = events
            self._last_refresh = datetime.now(UTC)

        self._save_cache(events)
        log.info("loaded %d economic events from calendar source", len(events))
        return events

    async def ensure_fresh(self) -> None:
        """Refresh events if cache is missing or stale, respecting error backoff."""
        now = datetime.now(UTC)

        # Backoff check: don't hammer on repeated errors
        if self._last_attempt is not None:
            elapsed = (now - self._last_attempt).total_seconds()
            if elapsed < self.retry_cooldown_s:
                return

        if (
            not self._events
            or self._last_refresh is None
            or (now - self._last_refresh).total_seconds() >= self.refresh_interval_s
        ):
            self._last_attempt = now
            try:
                await self.fetch_events()
            except Exception as exc:
                log.warning("failed to refresh economic calendar (backing off %ds): %s", int(self.retry_cooldown_s), exc)

    def check_blackout(
        self,
        now_dt: datetime | None = None,
        target_currencies: tuple[str, ...] = ("USD", "US"),
    ) -> tuple[bool, dict[str, Any] | None]:
        """Check if current time falls within pre/post blackout window of High-Impact news."""
        now = (now_dt or datetime.now(UTC)).astimezone(UTC)
        pre_delta = timedelta(minutes=self.pre_news_minutes)
        post_delta = timedelta(minutes=self.post_news_minutes)

        for e in self._events:
            if not e.is_high_impact:
                continue

            # Gold (XAUUSD) quote currency is USD — only blackout on USD high-impact events
            if target_currencies and e.country.upper() not in target_currencies:
                continue

            start_blackout = e.time - pre_delta
            end_blackout = e.time + post_delta

            if start_blackout <= now <= end_blackout:
                diff_m = round((e.time - now).total_seconds() / 60.0, 1)
                phase = "BEFORE" if diff_m >= 0 else "AFTER"
                return True, {
                    "title": e.title,
                    "country": e.country,
                    "impact": e.impact,
                    "event_time": e.time.isoformat(),
                    "minutes_to_event": diff_m,
                    "phase": phase,
                    "pre_m": self.pre_news_minutes,
                    "post_m": self.post_news_minutes,
                }

        return False, None

    def upcoming_events(
        self, now_dt: datetime | None = None, hours: int = 12
    ) -> list[dict[str, Any]]:
        """Return upcoming economic events within the next N hours."""
        now = (now_dt or datetime.now(UTC)).astimezone(UTC)
        horizon = now + timedelta(hours=hours)
        out = []
        for e in self._events:
            if now - timedelta(minutes=30) <= e.time <= horizon:
                out.append(
                    {
                        "title": e.title,
                        "impact": e.impact,
                        "time": e.time.isoformat(),
                        "minutes_away": round((e.time - now).total_seconds() / 60.0),
                    }
                )
        return out
