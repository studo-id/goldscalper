"""Synthetic Dollar Index (DXY) factor agent.

Computes a geometric synthetic DXY from EURUSD/USDJPY/GBPUSD (the three majors
covering >83% of the index) and maps dollar strength / risk regime to a gold
bias. Pure-python reimplementation of the read-only reference
``AcengGold/core/multi_tf_consensus.py`` (never imported, never edited).
"""

from __future__ import annotations

from typing import Any

from agents.base import AgentSignal
from agents.divisions.timeframe.base import TimeframeAgent
from agents.state import VOTE_BUY, VOTE_NEUTRAL, VOTE_SELL, SharedState

DEFAULT_DXY = 103.0
DXY_BEARISH_USD_DELTA = -0.15
DXY_BULLISH_USD_DELTA = 0.15
VIX_RISK_OFF = 20.0


def calculate_synthetic_dxy(eurusd: float, usdjpy: float, gbpusd: float) -> float:
    """Geometric synthetic DXY: ``56.56 · EURUSD^-0.576 · USDJPY^0.136 · GBPUSD^-0.119``."""
    if eurusd <= 0 or usdjpy <= 0 or gbpusd <= 0:
        return DEFAULT_DXY
    try:
        value = 56.56 * (eurusd**-0.576) * (usdjpy**0.136) * (gbpusd**-0.119)
    except (OverflowError, ValueError):  # pragma: no cover - defensive
        return DEFAULT_DXY
    return round(float(value), 2)


def evaluate_macro_sentiment(
    dxy_current: float,
    dxy_baseline: float | None = None,
    vix_current: float | None = None,
) -> dict[str, Any]:
    """Map DXY direction + VIX to a gold macro bias and score modifier."""
    dxy_base = dxy_baseline if dxy_baseline is not None else dxy_current
    dxy_delta = round(dxy_current - dxy_base, 2)

    if dxy_delta <= DXY_BEARISH_USD_DELTA:
        dxy_sentiment = "BEARISH_USD"
        gold_bias = "BULLISH"
    elif dxy_delta >= DXY_BULLISH_USD_DELTA:
        dxy_sentiment = "BULLISH_USD"
        gold_bias = "BEARISH"
    else:
        dxy_sentiment = "NEUTRAL"
        gold_bias = "NEUTRAL"

    vix = vix_current if (vix_current is not None and vix_current > 0) else 15.0
    risk_off = vix >= VIX_RISK_OFF

    modifier = 0.0
    if gold_bias == "BULLISH":
        modifier += 8.0
    elif gold_bias == "BEARISH":
        modifier -= 8.0
    if risk_off:
        modifier += 7.0

    return {
        "dxy_current": dxy_current,
        "dxy_delta": dxy_delta,
        "dxy_sentiment": dxy_sentiment,
        "gold_macro_bias": gold_bias,
        "vix_value": vix,
        "risk_mode": "RISK_OFF" if risk_off else "RISK_ON",
        "safe_haven_active": risk_off,
        "score_modifier": round(modifier, 1),
    }


class SyntheticDXYAgent(TimeframeAgent):
    """Macro cross-asset factor: dollar strength / risk regime → gold bias."""

    id = "TF-DXY-Synthetic"
    timeframe = None  # cross-asset factor, not a single timeframe

    async def evaluate(self, state: SharedState) -> AgentSignal:
        eurusd = state.extra.get("eurusd")
        usdjpy = state.extra.get("usdjpy")
        gbpusd = state.extra.get("gbpusd")
        if None in (eurusd, usdjpy, gbpusd):
            return self.neutral(
                "missing FX majors (eurusd/usdjpy/gbpusd)",
                timeframe=None,
            )

        dxy = calculate_synthetic_dxy(float(eurusd), float(usdjpy), float(gbpusd))
        sentiment = evaluate_macro_sentiment(
            dxy,
            dxy_baseline=state.extra.get("dxy_baseline"),
            vix_current=state.extra.get("vix"),
        )
        gold_bias = sentiment["gold_macro_bias"]
        if gold_bias == "BULLISH":
            vote = VOTE_BUY
        elif gold_bias == "BEARISH":
            vote = VOTE_SELL
        else:
            vote = VOTE_NEUTRAL

        return self.signal(
            vote=vote,
            confidence=0.70 if vote else 0.50,
            reasoning=f"synthetic DXY {sentiment['dxy_sentiment']} → gold {gold_bias}",
            timeframe=None,
            metadata={**sentiment, "dxy": dxy},
        )


__all__ = [
    "SyntheticDXYAgent",
    "calculate_synthetic_dxy",
    "evaluate_macro_sentiment",
]
