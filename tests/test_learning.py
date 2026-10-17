"""Tests for the learning loop (regime, analyzer, bandit, patterns)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agents.learning import (
    REGIME_RANGE,
    REGIME_TREND_DOWN,
    REGIME_TREND_UP,
    REGIME_VOLATILE,
    BanditOptimizer,
    PatternLibrary,
    analyze,
    classify,
    classify_bars,
)
from agents.learning.post_trade_analyzer import (
    CAUSE_ADVERSE,
    CAUSE_CONFIRMED,
    CAUSE_REGIME,
    CAUSE_SPREAD,
    OUTCOME_BREAKEVEN,
    OUTCOME_LOSS,
    OUTCOME_WIN,
)
from agents.orchestrator import Orchestrator
from agents.registry import AgentRegistry
from core.market_data import Bars, Candle, tf_seconds

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)


# --- regime --------------------------------------------------------------------


def test_classify_pure() -> None:
    assert classify(atr_pct=0.01, slope_pct=0.0) == REGIME_VOLATILE
    assert classify(atr_pct=0.001, slope_pct=0.005) == REGIME_TREND_UP
    assert classify(atr_pct=0.001, slope_pct=-0.005) == REGIME_TREND_DOWN
    assert classify(atr_pct=0.001, slope_pct=0.00001) == REGIME_RANGE


def _steep_up() -> Bars:
    rows = [
        Candle("XAUUSD", "M15", BASE + timedelta(seconds=tf_seconds("M15") * i),
               2350 + 5 * i, 2355 + 5 * i, 2348 + 5 * i, 2353 + 5 * i)
        for i in range(25)
    ]
    return Bars.from_rows(rows)


def test_classify_bars_trend() -> None:
    assert classify_bars(_steep_up()) == REGIME_TREND_UP


# --- analyzer ------------------------------------------------------------------


def test_analyze_win() -> None:
    card = analyze({"id": "t1", "pnl": 20.0, "direction": "BUY"}, {"risk_amount": 10.0})
    assert card.outcome == OUTCOME_WIN
    assert card.root_cause == CAUSE_CONFIRMED
    assert card.score == 2.0


def test_analyze_loss_spread() -> None:
    card = analyze({"id": "t2", "pnl": -10.0}, {"spread_points": 100})
    assert card.outcome == OUTCOME_LOSS
    assert card.root_cause == CAUSE_SPREAD


def test_analyze_loss_range() -> None:
    card = analyze({"id": "t3", "pnl": -8.0}, {"regime": "range", "spread_points": 10})
    assert card.root_cause == CAUSE_REGIME


def test_analyze_loss_adverse() -> None:
    card = analyze({"id": "t4", "pnl": -5.0, "duration_s": 120}, {"spread_points": 10})
    assert card.root_cause == CAUSE_ADVERSE


def test_analyze_breakeven() -> None:
    card = analyze({"id": "t5", "pnl": 0.0})
    assert card.outcome == OUTCOME_BREAKEVEN


# --- bandit --------------------------------------------------------------------


def test_bandit_prefers_winner() -> None:
    b = BanditOptimizer(exploration=0.1)
    for _ in range(5):
        b.update("winner", 1.0)
        b.update("loser", -1.0)
    assert b.winrate("winner") > b.winrate("loser")
    assert b.suggest_weight("winner", 1.0) > b.suggest_weight("loser", 1.0)


def test_bandit_clamps_delta() -> None:
    b = BanditOptimizer(exploration=1.0, weight_max_delta_pct=20.0)
    for _ in range(20):
        b.update("a", 1.0)
    assert b.suggest_weight("a", 1.0) == 1.2


def test_bandit_deterministic() -> None:
    b1 = BanditOptimizer(seed=3)
    b2 = BanditOptimizer(seed=3)
    assert b1.sample("x") == b2.sample("x")


# --- pattern library -----------------------------------------------------------


def test_pattern_library_rollup() -> None:
    lib = PatternLibrary()
    lib.add(analyze({"id": "a", "pnl": 10.0}, {"regime": "range"}))
    lib.add(analyze({"id": "b", "pnl": -10.0}, {"regime": "range", "spread_points": 100}))
    entries = lib.entries()
    assert entries  # at least one bucket
    total = sum(e.count for e in entries)
    assert total == 2


# --- orchestrator hook ---------------------------------------------------------


class FakeLessonRepo:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def save(self, fields: dict) -> None:
        self.rows.append(fields)


async def test_orchestrator_on_trade_closed() -> None:
    repo = FakeLessonRepo()
    bandit = BanditOptimizer()
    lib = PatternLibrary()
    orch = Orchestrator(
        AgentRegistry(),
        lesson_repo=repo,
        bandit=bandit,
        pattern_library=lib,
        broadcast=False,
    )
    card = await orch.on_trade_closed(
        {"id": "t9", "pnl": 15.0, "direction": "BUY"},
        {"regime": "trend_up", "agent_ids": ["TF-M1-Sniper"]},
    )
    assert card is not None
    assert card.outcome == OUTCOME_WIN
    assert len(repo.rows) == 1
    assert bandit.winrate("TF-M1-Sniper") > 0.5
    assert lib.entries()


async def test_orchestrator_on_trade_closed_handles_bad_trade() -> None:
    orch = Orchestrator(AgentRegistry(), broadcast=False)
    card = await orch.on_trade_closed({"id": "t10", "pnl": -5.0})
    assert card is not None
    assert card.outcome == OUTCOME_LOSS
