"""Learning loop: post-trade analysis, bandit weight tuning, regimes, patterns."""

from __future__ import annotations

from agents.learning.bandit_optimizer import BanditOptimizer
from agents.learning.pattern_library import PatternLibrary, PatternStat
from agents.learning.post_trade_analyzer import LessonCard, analyze
from agents.learning.regime_classifier import (
    REGIME_RANGE,
    REGIME_TREND_DOWN,
    REGIME_TREND_UP,
    REGIME_VOLATILE,
    REGIMES,
    classify,
    classify_bars,
    classify_state,
)

__all__ = [
    "BanditOptimizer",
    "PatternLibrary",
    "PatternStat",
    "LessonCard",
    "analyze",
    "REGIME_TREND_UP",
    "REGIME_TREND_DOWN",
    "REGIME_RANGE",
    "REGIME_VOLATILE",
    "REGIMES",
    "classify",
    "classify_bars",
    "classify_state",
]
