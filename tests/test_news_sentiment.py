"""Tests for NewsSentimentService (RSS news feed & macro regime scoring)."""

from __future__ import annotations

from pathlib import Path
import pytest

from core.news_sentiment_service import NewsSentimentService


def test_score_text_bullish() -> None:
    srv = NewsSentimentService()
    sent, macro = srv.score_text("Gold price surges to record high as Fed signals rate cut")
    assert sent > 0.0
    assert macro > 0.0


def test_score_text_bearish() -> None:
    srv = NewsSentimentService()
    sent, macro = srv.score_text("Gold price slumps as strong dollar and sticky inflation point to rate hike")
    assert sent < 0.0
    assert macro < 0.0


def test_get_state_defaults() -> None:
    srv = NewsSentimentService(cache_path=Path("non_existent_cache.json"))
    state = srv.get_state()
    assert state["news_sentiment"] == 0.0
    assert state["macro_bias"] == "neutral"
