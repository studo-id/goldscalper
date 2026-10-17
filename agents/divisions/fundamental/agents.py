"""Fundamental division agents (IMPLEMENTATION_PLAN Phase 6.7–6.10).

    6.7  Fund-Calendar      — news blackout windows
    6.8  Fund-NewsSentiment — pre-computed sentiment (optional async LLM)
    6.9  Fund-MacroRegime   — rates / inflation stance
    6.10 Fund-Intermarket   — DXY / equities / bonds
"""

from __future__ import annotations

from typing import Any

from agents.base import AgentSignal
from agents.divisions.fundamental.base import FundamentalAgent
from agents.state import VETO_BUY, VETO_SELL, VOTE_BUY, VOTE_NEUTRAL, VOTE_SELL, SharedState

_MIN_CONF = 0.4
_MAX_CONF = 0.7


class Calendar(FundamentalAgent):
    id = "Fund-Calendar"

    async def evaluate(self, state: SharedState) -> AgentSignal:
        blackout = state.is_news_blackout()
        current_news = state.extra.get("current_news")
        events = state.extra.get("calendar_events") or []
        high_impact = sum(1 for e in events if str(e.get("impact", "")).lower() == "high")

        meta: dict[str, Any] = {
            "blackout": blackout,
            "current_news": current_news,
            "events_count": len(events),
            "high_impact": high_impact,
            "high_impact_count": high_impact,
        }

        if blackout:
            title = current_news.get("title", "High-Impact News") if current_news else "High-Impact News"
            phase = current_news.get("phase", "ACTIVE") if current_news else "ACTIVE"
            mins = current_news.get("minutes_to_event", 0) if current_news else 0
            return self.signal(
                VOTE_NEUTRAL,
                1.0,
                f"NEWS BLACKOUT: {title} ({phase} {abs(mins):.0f}m)",
                meta,
                veto=VETO_BUY,
                timeframe=None,
            )

        next_event = events[0] if events else None
        next_str = (
            f"next: {next_event.get('title')} in {next_event.get('minutes_away')}m"
            if next_event
            else "no upcoming events"
        )
        return self.signal(
            VOTE_NEUTRAL,
            0.50,
            f"calendar clear (high_impact={high_impact}, {next_str})",
            meta,
            timeframe=None,
        )


class NewsSentiment(FundamentalAgent):
    id = "Fund-NewsSentiment"

    async def evaluate(self, state: SharedState) -> AgentSignal:
        raw = state.extra.get("news_sentiment")
        if raw is None:
            return self.neutral("no sentiment feed", timeframe=None)
        score = float(raw)
        conf = min(_MAX_CONF, _MIN_CONF + abs(score) * 0.3)
        meta = {"news_sentiment": round(score, 3)}
        if score >= 0.2:
            return self.signal(VOTE_BUY, conf, "positive news sentiment", meta, timeframe=None)
        if score <= -0.2:
            return self.signal(VOTE_SELL, conf, "negative news sentiment", meta, timeframe=None)
        return self.signal(VOTE_NEUTRAL, 0.5, "neutral sentiment", meta, timeframe=None)


class MacroRegime(FundamentalAgent):
    id = "Fund-MacroRegime"

    async def evaluate(self, state: SharedState) -> AgentSignal:
        bias = state.extra.get("macro_bias")
        score = state.extra.get("macro_score")
        if bias is None and score is None:
            return self.neutral("no macro input", timeframe=None)

        meta: dict[str, Any] = {"macro_bias": bias, "macro_score": score}
        dovish = bias == "dovish" or (isinstance(score, int | float) and score > 0)
        hawkish = bias == "hawkish" or (isinstance(score, int | float) and score < 0)
        if dovish:
            return self.signal(VOTE_BUY, 0.60, "dovish / easing stance", meta, timeframe=None)
        if hawkish:
            return self.signal(VOTE_SELL, 0.60, "hawkish / tightening stance", meta, timeframe=None)
        return self.signal(VOTE_NEUTRAL, 0.5, "neutral macro regime", meta, timeframe=None)


class Intermarket(FundamentalAgent):
    id = "Fund-Intermarket"

    async def evaluate(self, state: SharedState) -> AgentSignal:
        dxy = state.extra.get("dxy_delta")
        us10y = state.extra.get("us10y_delta")
        spx = state.extra.get("spx_delta")
        if dxy is None and us10y is None and spx is None:
            return self.neutral("no intermarket data", timeframe=None)

        def _sign(value: Any) -> int:
            if value is None:
                return 0
            return 1 if value > 0 else (-1 if value < 0 else 0)

        score = -_sign(dxy) - _sign(us10y) + _sign(spx)
        meta = {"dxy_delta": dxy, "us10y_delta": us10y, "spx_delta": spx, "score": score}
        if score > 0:
            return self.signal(VOTE_BUY, 0.60, f"intermarket bullish (score {score})", meta)
        if score < 0:
            return self.signal(VOTE_SELL, 0.60, f"intermarket bearish (score {score})", meta)
        return self.signal(VOTE_NEUTRAL, 0.5, "intermarket mixed", meta)


FUNDAMENTAL_AGENT_CLASSES: tuple[type[FundamentalAgent], ...] = (
    Calendar,
    NewsSentiment,
    MacroRegime,
    Intermarket,
)


__all__ = [
    "Calendar",
    "NewsSentiment",
    "MacroRegime",
    "Intermarket",
    "FUNDAMENTAL_AGENT_CLASSES",
]
