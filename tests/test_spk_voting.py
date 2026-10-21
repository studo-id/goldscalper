"""Tests for SPK weighted voting (Phase 1.5)."""

from agents.base import AgentSignal
from agents.state import VOTE_BUY, VOTE_NEUTRAL, VOTE_SELL
from spk.decision import (
    ACTION_BUY,
    ACTION_HOLD,
    ACTION_SELL,
    STRENGTH_NONE,
    STRENGTH_NORMAL,
    STRENGTH_STRONG,
)
from spk.voting import SPKThresholds, action_for_score, aggregate, confidence_from


def _sig(vote: int, conf: float, weight: float = 1.0, division: str = "timeframe") -> AgentSignal:
    return AgentSignal(
        agent_id=f"a-{vote}-{conf}",
        division=division,
        vote=vote,
        confidence=conf,
        weight=weight,
    )


def test_aggregate_net_long() -> None:
    result = aggregate([
        _sig(VOTE_BUY, 0.8, 1.0),
        _sig(VOTE_BUY, 0.5, 1.0),
        _sig(VOTE_SELL, 0.2, 1.0),
        _sig(VOTE_NEUTRAL, 0.9, 1.0),
    ])
    assert result.score == round(0.8 + 0.5 - 0.2, 4)
    assert result.buy_score == 1.3
    assert result.sell_score == 0.2
    assert result.participation == 3  # neutral with no vote not counted


def test_aggregate_empty() -> None:
    result = aggregate([])
    assert result.score == 0.0
    assert result.agreement == 0.0
    assert result.participation == 0


def test_weight_scales_contribution() -> None:
    result = aggregate([_sig(VOTE_BUY, 1.0, weight=2.0)])
    assert result.score == 2.0


def test_action_thresholds() -> None:
    t = SPKThresholds(strong=2.0, weak=0.5)
    assert action_for_score(2.5, t) == (ACTION_BUY, STRENGTH_STRONG)
    assert action_for_score(1.0, t) == (ACTION_BUY, STRENGTH_NORMAL)
    assert action_for_score(-1.0, t) == (ACTION_SELL, STRENGTH_NORMAL)
    assert action_for_score(-3.0, t) == (ACTION_SELL, STRENGTH_STRONG)
    assert action_for_score(0.3, t) == (ACTION_HOLD, STRENGTH_NONE)
    assert action_for_score(-0.5, t) == (ACTION_HOLD, STRENGTH_NONE)  # boundary -> hold


def test_confidence_bounds_and_agreement() -> None:
    unanimous = aggregate([_sig(VOTE_BUY, 1.0) for _ in range(6)])
    mixed = aggregate([_sig(VOTE_BUY, 1.0), _sig(VOTE_SELL, 1.0)])
    t = SPKThresholds()
    assert 0.0 <= confidence_from(mixed, t) <= 1.0
    # Unanimous, large magnitude, full participation -> high confidence.
    assert confidence_from(unanimous, t) > confidence_from(mixed, t)
    assert confidence_from(mixed, t) < 0.6


def test_action_for_score_target_locked_or_reached_holds() -> None:
    t = SPKThresholds(strong=2.0, weak=0.5)
    # High score that normally triggers STRONG BUY
    score = 3.0
    # If target is locked, SPK holds
    assert action_for_score(score, t, portfolio_state={"daily_profit_locked": True}) == (ACTION_HOLD, STRENGTH_NONE)
    # If remaining target is 0, SPK holds
    assert action_for_score(score, t, portfolio_state={"remaining_target_usd": 0.0}) == (ACTION_HOLD, STRENGTH_NONE)


def test_action_for_score_drawdown_scales_consensus_bar() -> None:
    t = SPKThresholds(strong=2.0, weak=0.5)
    # Score 0.65 is normally a NORMAL BUY when weak=0.5
    assert action_for_score(0.65, t) == (ACTION_BUY, STRENGTH_NORMAL)
    # In drawdown (-6.0%), threshold increases by +40%, so weak=0.70. Score 0.65 is now filtered to HOLD!
    assert action_for_score(0.65, t, portfolio_state={"daily_pnl_pct": -6.0}) == (ACTION_HOLD, STRENGTH_NONE)


def test_action_for_score_finish_line_proximity() -> None:
    t = SPKThresholds(strong=2.0, weak=0.5)
    # Score 0.55 is normally a NORMAL BUY
    assert action_for_score(0.55, t) == (ACTION_BUY, STRENGTH_NORMAL)
    # Right at the finish line (only $5 left), entry bar is tightened to avoid risking target
    assert action_for_score(0.55, t, portfolio_state={"remaining_target_usd": 5.0}) == (ACTION_HOLD, STRENGTH_NONE)


def test_action_for_score_m1_sniper_fast_lane() -> None:
    t = SPKThresholds(strong=2.0, weak=0.5)
    # M1 Sniper signal with high conviction (0.75)
    m1_sig = AgentSignal(
        agent_id="TF-M1-Sniper",
        division="timeframe",
        vote=1,
        confidence=0.75,
        weight=1.2,
    )
    result = aggregate([m1_sig])
    assert result.has_m1_sniper_buy is True

    # Modest score 0.40 would normally be rejected by lone agent threshold (0.55),
    # but with M1 Fast-Lane active, it smoothly executes BUY!
    action, strength = action_for_score(0.40, t, result=result)
    assert action == ACTION_BUY
    assert strength == STRENGTH_NORMAL

