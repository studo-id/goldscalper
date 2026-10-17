"""Real-time News Sentiment and Macro Regime service for Gold (XAUUSD).

Fetches top financial headlines via financial RSS feeds (Google Finance / Yahoo Finance),
analyzes directional sentiment (bullish vs bearish gold), detects Fed macro regime bias
(dovish vs hawkish), and persists cache locally to supply Fund-NewsSentiment and
Fund-MacroRegime agents.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

import httpx

from config.logging import get_logger

UTC = timezone.utc
log = get_logger("core.news_sentiment")

PRIMARY_RSS_URL = (
    "https://news.google.com/rss/search?q=gold+price+OR+federal+reserve&hl=en-US&gl=US&ceid=US:en"
)
FALLBACK_RSS_URL = "https://finance.yahoo.com/rss/headline?s=GC=F"
CACHE_PATH = Path("data/sentiment_cache.json")

# Gold-specific sentiment lexicons
BULLISH_KEYWORDS = {
    "rebound", "rebounds", "surge", "surges", "surging", "rally", "rallies",
    "rallying", "jump", "jumps", "gain", "gains", "record high", "all-time high",
    "target raised", "safe haven", "safe-haven", "crisis", "escalation", "war",
    "rate cut", "cuts rates", "dovish", "easing", "soar", "soars", "inflation hedge",
    "smash yields", "falling yields", "weak dollar", "dollar slips", "dollar drops",
}

BEARISH_KEYWORDS = {
    "drop", "drops", "dropping", "fall", "falls", "falling", "slump", "slumps",
    "slide", "slides", "tumble", "tumbles", "selloff", "sell-off", "profit taking",
    "strengthens", "strong dollar", "dollar rallies", "dollar surges", "rate hike",
    "hikes rates", "hawkish", "tightening", "cpi heats up", "higher for longer",
    "yields rise", "yields surge", "yields jump", "downward pressure", "drifts lower",
}

DOVISH_KEYWORDS = {"rate cut", "cut rates", "dovish", "easing", "cool inflation", "cooling inflation", "pause"}
HAWKISH_KEYWORDS = {"rate hike", "hike rates", "hawkish", "tightening", "cpi heats", "sticky inflation", "higher for longer"}


class NewsSentimentService:
    """Manages news RSS fetching, sentiment parsing, and macro bias detection."""

    def __init__(
        self,
        feed_url: str = PRIMARY_RSS_URL,
        fallback_url: str = FALLBACK_RSS_URL,
        refresh_interval_s: float = 900.0,  # 15 minutes
        cache_path: Path = CACHE_PATH,
    ) -> None:
        self.feed_url = feed_url
        self.fallback_url = fallback_url
        self.refresh_interval_s = refresh_interval_s
        self.retry_cooldown_s = 300.0
        self.cache_path = cache_path

        self._sentiment_score: float = 0.0
        self._macro_bias: str = "neutral"
        self._macro_score: float = 0.0
        self._headlines: list[dict[str, Any]] = []
        self._last_refresh: datetime | None = None
        self._last_attempt: datetime | None = None
        self._lock = asyncio.Lock()

        self._load_cache()

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._sentiment_score = float(data.get("news_sentiment", 0.0))
            self._macro_bias = str(data.get("macro_bias", "neutral"))
            self._macro_score = float(data.get("macro_score", 0.0))
            self._headlines = data.get("headlines", [])
            self._last_refresh = datetime.now(UTC)
            log.info("loaded cached news sentiment (score=%s, bias=%s)", self._sentiment_score, self._macro_bias)
        except Exception as exc:
            log.warning("could not load sentiment cache: %s", exc)

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "news_sentiment": self._sentiment_score,
                "macro_bias": self._macro_bias,
                "macro_score": self._macro_score,
                "headlines": self._headlines,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as exc:
            log.debug("could not save sentiment cache: %s", exc)

    def score_text(self, text: str) -> tuple[float, float]:
        """Score text for gold sentiment (-1.0 to 1.0) and macro score (-1.0 to 1.0)."""
        lower = text.lower()

        bull_hits = sum(1 for kw in BULLISH_KEYWORDS if kw in lower)
        bear_hits = sum(1 for kw in BEARISH_KEYWORDS if kw in lower)
        total_hits = bull_hits + bear_hits
        sent_score = (bull_hits - bear_hits) / max(1, total_hits) if total_hits > 0 else 0.0

        dov_hits = sum(1 for kw in DOVISH_KEYWORDS if kw in lower)
        hawk_hits = sum(1 for kw in HAWKISH_KEYWORDS if kw in lower)
        total_macro = dov_hits + hawk_hits
        macro_score = (dov_hits - hawk_hits) / max(1, total_macro) if total_macro > 0 else 0.0

        return sent_score, macro_score

    async def fetch_and_analyze(self) -> None:
        """Fetch RSS feed, extract items, score headlines, and update state."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }

        xml_text = None
        for url in (self.feed_url, self.fallback_url):
            try:
                async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200 and len(resp.text) > 100:
                        xml_text = resp.text
                        break
            except Exception as exc:
                log.debug("failed to fetch RSS from %s: %s", url, exc)

        if not xml_text:
            raise RuntimeError("All RSS news feeds failed to return data")

        try:
            root = ET.fromstring(xml_text)
            items = root.findall(".//item")
        except Exception as exc:
            raise ValueError(f"Failed to parse RSS XML: {exc}") from exc

        parsed_headlines = []
        sent_scores = []
        macro_scores = []

        for item in items[:15]:
            title_node = item.find("title")
            if title_node is None or not title_node.text:
                continue
            title = title_node.text.strip()
            # Clean HTML tags if any
            clean_title = re.sub(r"<[^>]+>", "", title)

            s_score, m_score = self.score_text(clean_title)
            parsed_headlines.append({"title": clean_title, "sentiment": s_score, "macro": m_score})
            sent_scores.append(s_score)
            if m_score != 0.0:
                macro_scores.append(m_score)

        avg_sent = sum(sent_scores) / len(sent_scores) if sent_scores else 0.0
        avg_macro = sum(macro_scores) / len(macro_scores) if macro_scores else 0.0

        if avg_macro >= 0.2:
            bias = "dovish"
        elif avg_macro <= -0.2:
            bias = "hawkish"
        else:
            bias = "neutral"

        async with self._lock:
            self._sentiment_score = round(avg_sent, 2)
            self._macro_score = round(avg_macro, 2)
            self._macro_bias = bias
            self._headlines = parsed_headlines
            self._last_refresh = datetime.now(UTC)

        self._save_cache()
        log.info(
            "analyzed %d headlines: sentiment=%.2f, macro_bias=%s (score=%.2f)",
            len(parsed_headlines),
            self._sentiment_score,
            self._macro_bias,
            self._macro_score,
        )

    async def ensure_fresh(self) -> None:
        """Refresh sentiment if stale, respecting retry cooldown."""
        now = datetime.now(UTC)

        if self._last_attempt is not None:
            elapsed = (now - self._last_attempt).total_seconds()
            if elapsed < self.retry_cooldown_s:
                return

        if (
            self._last_refresh is None
            or (now - self._last_refresh).total_seconds() >= self.refresh_interval_s
        ):
            self._last_attempt = now
            try:
                await self.fetch_and_analyze()
            except Exception as exc:
                log.warning("failed to refresh news sentiment: %s", exc)

    def get_state(self) -> dict[str, Any]:
        """Return state dictionary for injection into SharedState.extra."""
        top_headlines = [h["title"] for h in self._headlines[:3]]
        return {
            "news_sentiment": self._sentiment_score,
            "macro_bias": self._macro_bias,
            "macro_score": self._macro_score,
            "news_headlines": top_headlines,
        }
