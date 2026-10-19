"""Tests for the risk division (6 vote-neutral agents) and pre-trade risk gate."""

from __future__ import annotations

from datetime import datetime, timedelta
from core.clock import UTC

from agents.divisions.risk import (
    CostMonitor,
    DrawdownGuard,
    EntryTiming,
    PositionSizer,
    StopLoss,
    TakeProfit,
    build_risk_agents,
    proposed_stop_distance,
)
from agents.state import VOTE_NEUTRAL, SharedState
from config.settings import settings
from core.market_data import Candle, tf_seconds
from execution import risk_gate
from spk.decision import ACTION_BUY, ACTION_SELL, STRENGTH_STRONG, SPKDecision

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)

# Every M1 bar spans 2.0 ($) => ATR(14) == 2.0 => SL distance 2.0 * 1.2 == 2.4
_FLAT_M1 = [(2350.0, 2351.0, 2349.0, 2350.0) for _ in range(20)]


def m1(rows: list[tuple[float, float, float, float]] = _FLAT_M1) -> list[Candle]:
    step = tf_seconds("M1")
    return [
        Candle("XAUUSD", "M1", BASE + timedelta(seconds=step * i), o, h, low, c)
        for i, (o, h, low, c) in enumerate(rows)
    ]


def state(**kw: object) -> SharedState:
    frames = kw.pop("frames", {"M1": m1()})
    return SharedState(symbol="XAUUSD", frames=frames, **kw)  # type: ignore[arg-type]


async def risk_votes(st: SharedState) -> list:
    return [await agent.evaluate(st) for agent in build_risk_agents()]


# --- agents --------------------------------------------------------------------


def test_factory_returns_six_agents() -> None:
    agents = build_risk_agents()
    assert {a.id for a in agents} == {
        "Risk-PositionSizer",
        "Risk-StopLoss",
        "Risk-TakeProfit",
        "Risk-EntryTiming",
        "Risk-DrawdownGuard",
        "Risk-CostMonitor",
    }
    assert all(a.division == "risk" for a in agents)
    assert all(a.default_weight == 2.0 for a in agents)


async def test_agents_are_vote_neutral() -> None:
    votes = await risk_votes(state(equity=10000.0, spread_points=20))
    assert all(v.vote == VOTE_NEUTRAL for v in votes)
    assert all(v.confidence == 0.0 for v in votes)


async def test_position_sizer_math() -> None:
    sig = await PositionSizer().evaluate(state(equity=10000.0))
    # risk 0.5% of 10000 = 50; min spread-floor sl = 2.50; value/lot = 2.5 * 100 = 250; raw 50/250 = 0.20
    assert sig.metadata["size"] == 0.20
    assert sig.metadata["sl_distance"] == 2.50
    assert sig.metadata["risk_amount"] == 50.0


async def test_position_sizer_without_equity_is_zero() -> None:
    sig = await PositionSizer().evaluate(state(equity=0.0))
    assert sig.metadata["size"] == 0.0


async def test_stop_loss_distance_and_time_stop() -> None:
    sig = await StopLoss().evaluate(state())
    assert sig.metadata["sl_distance"] == 2.50
    assert sig.metadata["time_stop_s"] == settings.max_hold_seconds


async def test_take_profit_rr_and_partials() -> None:
    sig = await TakeProfit().evaluate(state())
    assert sig.metadata["rr"] == 1.5
    assert sig.metadata["tp_distance"] == 3.75  # 2.5 * 1.5
    assert len(sig.metadata["partials"]) == 2


async def test_take_profit_dynamic_defense_and_growth_modes() -> None:
    # Defense mode (<0%): RR drops to 1.30 for fast profit banking
    sig_def = await TakeProfit().evaluate(state(daily_pnl_pct=-2.0))
    assert sig_def.metadata["rr"] == 1.30
    assert sig_def.metadata["portfolio_mode"].startswith("DEFENSE")

    # Growth mode (>=3%): RR expands to 2.0 to let winners run
    sig_growth = await TakeProfit().evaluate(state(daily_pnl_pct=5.0))
    assert sig_growth.metadata["rr"] == 2.0
    assert sig_growth.metadata["portfolio_mode"].startswith("GROWTH")

    # Finish line proximity (rem <= $20): calibrates to sprint goal
    sig_finish = await TakeProfit().evaluate(state(extra={"remaining_target_usd": 4.50}))
    assert sig_finish.metadata["tp_distance"] == 4.50
    assert "Finish Line" in sig_finish.metadata["portfolio_mode"]

    # High-conviction runner in DEFENSE mode expands TP to capture runners
    sig_def_high = await TakeProfit().evaluate(state(daily_pnl_pct=-1.5, extra={"spk_confidence": 0.75}))
    assert sig_def_high.metadata["rr"] == 1.80
    assert sig_def_high.metadata["tp_distance"] >= 7.50
    assert "HIGH-CONVICTION RUNNER" in sig_def_high.metadata["portfolio_mode"]


async def test_position_sizer_high_conviction_tier_in_defense() -> None:
    # High-conviction Grade A+ setup in DEFENSE allocates 0.03-0.04 recovery lot
    st_high = state(
        equity=10000.0,
        balance_start_of_day=10000.0,
        daily_pnl_pct=-1.0,
        daily_realized_pnl=-100.0,
        extra={"spk_confidence": 0.75},
    )
    sig_high = await PositionSizer().evaluate(st_high)
    assert sig_high.metadata["high_conviction"] is True
    assert sig_high.metadata["size"] >= 0.03


async def test_position_sizer_balanced_mode_lot_floor_with_wide_atr() -> None:
    # In BALANCED mode (0% <= daily_pnl_pct < 3%), lot must be >= 0.02 even with wide ATR
    st_bal = state(
        equity=8870.0,
        balance_start_of_day=8870.0,
        daily_pnl_pct=0.5,
        daily_realized_pnl=44.0,
        extra={"live_avg_win": 1.20},
    )
    sig_bal = await PositionSizer().evaluate(st_bal)
    assert sig_bal.metadata["portfolio_mode"] == "BALANCED"
    assert sig_bal.metadata["size"] >= 0.02


async def test_position_sizer_growth_mode_scales_up() -> None:
    # In GROWTH mode (daily_pnl_pct >= 3%), lot scales up using house money (>= 0.03)
    st_growth = state(
        equity=10000.0,
        balance_start_of_day=10000.0,
        daily_pnl_pct=4.0,
        daily_realized_pnl=400.0,
    )
    sig_growth = await PositionSizer().evaluate(st_growth)
    assert sig_growth.metadata["portfolio_mode"] == "GROWTH"
    assert sig_growth.metadata["size"] >= 0.03


async def test_position_sizer_finish_line_tapers() -> None:
    # Near sprint finish line (rem <= 10% of target), lot tapers smoothly down from full 0.20 lot to 0.05 lot
    st_finish = state(
        equity=10000.0,
        balance_start_of_day=10000.0,
        daily_pnl_pct=2.8,
        daily_realized_pnl=3485.0,
        extra={"remaining_target_usd": 15.0},
    )
    sig_finish = await PositionSizer().evaluate(st_finish)
    assert sig_finish.metadata["size"] <= 0.05
    assert sig_finish.metadata["size"] < 0.20



async def test_entry_timing_market_when_tight() -> None:
    sig = await EntryTiming().evaluate(state(spread_points=10))
    assert sig.metadata["order_type"] == "market"
    assert sig.metadata["spread_ok"] is True


async def test_entry_timing_limit_when_wide() -> None:
    sig = await EntryTiming().evaluate(state(spread_points=40))
    assert sig.metadata["order_type"] == "limit"
    assert sig.metadata["spread_ok"] is True  # still within hard max


async def test_entry_timing_friction_rebate_deduction() -> None:
    # 2.0 lots traded -> 2.0 * $6 = $12 rebate
    # Friction cost = $15 -> Net friction = $3
    # Gross profit = $20 -> Ratio = 3 / 20 = 15% (<= 25% threshold)
    st = state(
        daily_gross_profit=20.0,
        daily_friction_cost=15.0,
        daily_lots_traded=2.0,
        daily_pnl_pct=0.5,
    )
    sig = await EntryTiming().evaluate(st)
    assert sig.metadata["friction_blocked"] is False
    assert sig.metadata["friction_ratio"] == 15.0
    assert sig.metadata["spread_ok"] is True


async def test_entry_timing_friction_in_growth_expands_tp() -> None:
    # Net friction = $30, Gross = $100 -> Ratio = 30% (> 25% threshold)
    # But daily_pnl_pct = +2.0% (GROWTH/BALANCED mode) -> Do NOT block, expand TP
    st = state(
        daily_gross_profit=100.0,
        daily_friction_cost=30.0,
        daily_lots_traded=0.0,
        daily_pnl_pct=2.0,
    )
    sig = await EntryTiming().evaluate(st)
    assert sig.metadata["friction_blocked"] is False
    assert sig.metadata["adaptive_tp_expansion"] is True
    assert sig.metadata["spread_ok"] is True


async def test_entry_timing_friction_in_defense_mode_blocks() -> None:
    # Net friction = $30, Gross = $100 -> Ratio = 30% (> 25% threshold)
    # daily_pnl_pct = -1.5% (DEFENSE mode) -> Hard block
    st = state(
        daily_gross_profit=100.0,
        daily_friction_cost=30.0,
        daily_lots_traded=0.0,
        daily_pnl_pct=-1.5,
    )
    sig = await EntryTiming().evaluate(st)
    assert sig.metadata["friction_blocked"] is True
    assert sig.metadata["spread_ok"] is True  # Spread is fine, but friction blocks


async def test_cost_monitor_flags_wide_spread() -> None:
    sig = await CostMonitor().evaluate(state(spread_points=100))
    assert sig.metadata["cost_ok"] is False


async def test_drawdown_guard_halts_on_daily_loss() -> None:
    sig = await DrawdownGuard().evaluate(state(daily_pnl_pct=-3.5))
    assert sig.metadata["halt"] is True
    assert "daily" in (sig.metadata["reason"] or "")


async def test_drawdown_guard_halts_on_streak() -> None:
    sig = await DrawdownGuard().evaluate(state(consecutive_losses=4))
    assert sig.metadata["halt"] is True


async def test_drawdown_guard_ok() -> None:
    sig = await DrawdownGuard().evaluate(state(daily_pnl_pct=-1.0))
    assert sig.metadata["halt"] is False


def test_proposed_stop_distance_uses_atr() -> None:
    stop = proposed_stop_distance(state(), settings)
    assert stop["distance"] == 2.50
    assert stop["atr"] == 2.0
    assert stop["atr_tf"] == "M1"


# --- risk gate -----------------------------------------------------------------


async def _decision(action: str, confidence: float = 1.0, **kw: object) -> SPKDecision:
    st = state(equity=10000.0, spread_points=20)
    return SPKDecision(
        action=action,
        strength=STRENGTH_STRONG,
        score=3.0,
        confidence=confidence,
        entry=2350.0,
        votes=await risk_votes(st),
        **kw,  # type: ignore[arg-type]
    )


async def test_gate_stamps_buy_size_sl_tp() -> None:
    decision = await _decision(ACTION_BUY)
    result = risk_gate.evaluate(decision, state(equity=10000.0, spread_points=20))
    assert result.approved is True
    assert result.size > 0.0
    assert result.sl is not None and result.sl < 2350.0
    assert result.tp is not None and result.tp > 2350.0


async def test_gate_stamps_sell_sign() -> None:
    decision = await _decision(ACTION_SELL)
    result = risk_gate.evaluate(decision, state(equity=10000.0, spread_points=20))
    assert result.sl is not None and result.sl > 2350.0
    assert result.tp is not None and result.tp < 2350.0


async def test_gate_scales_size_by_confidence() -> None:
    decision = await _decision(ACTION_BUY, confidence=0.8)
    result = risk_gate.evaluate(decision, state(equity=10000.0, spread_points=20))
    assert 0.0 < result.size <= 0.20


async def test_gate_bypasses_double_shrinkage_on_high_conviction() -> None:
    st = state(equity=10000.0, spread_points=20)
    decision = await _decision(ACTION_BUY, confidence=0.75)
    for v in decision.votes:
        if v.agent_id == "Risk-PositionSizer":
            v.metadata["high_conviction"] = True
            v.metadata["size"] = 0.04
    result = risk_gate.evaluate(decision, st)
    assert result.size == 0.04


async def test_gate_preserves_small_defense_lots_without_crushing_to_one() -> None:
    st = state(equity=10000.0, spread_points=20)
    decision = await _decision(ACTION_BUY, confidence=0.50)
    for v in decision.votes:
        if v.agent_id == "Risk-PositionSizer":
            v.metadata["size"] = 0.02
    result = risk_gate.evaluate(decision, st)
    assert result.size == 0.02


async def test_gate_blocks_on_hold() -> None:
    decision = SPKDecision(action="HOLD")
    result = risk_gate.evaluate(decision, state())
    assert result.approved is False
    assert result.reason == "hold"


async def test_gate_blocks_on_drawdown_halt() -> None:
    st = state(equity=10000.0, daily_pnl_pct=-4.0)
    decision = SPKDecision(
        action=ACTION_BUY,
        confidence=1.0,
        entry=2350.0,
        votes=await risk_votes(st),
    )
    result = risk_gate.evaluate(decision, st)
    assert result.approved is False
    assert "drawdown" in (result.reason or "")


async def test_gate_blocks_on_wide_spread() -> None:
    st = state(equity=10000.0, spread_points=100)
    decision = SPKDecision(
        action=ACTION_BUY,
        confidence=1.0,
        entry=2350.0,
        votes=await risk_votes(st),
    )
    result = risk_gate.evaluate(decision, st)
    assert result.approved is False
    assert "spread" in (result.reason or "").lower()


async def test_gate_blocks_on_friction_guard_in_defense() -> None:
    st = state(
        equity=10000.0,
        spread_points=20,
        daily_pnl_pct=-1.0,
        daily_gross_profit=100.0,
        daily_friction_cost=40.0,
        daily_lots_traded=0.0,
    )
    decision = SPKDecision(
        action=ACTION_BUY,
        confidence=1.0,
        entry=2350.0,
        votes=await risk_votes(st),
    )
    result = risk_gate.evaluate(decision, st)
    assert result.approved is False
    assert "friction guard" in (result.reason or "")


async def test_gate_apply_sets_hard_veto_on_block() -> None:
    st = state(equity=10000.0, daily_pnl_pct=-4.0)
    decision = SPKDecision(
        action=ACTION_BUY,
        confidence=1.0,
        entry=2350.0,
        votes=await risk_votes(st),
    )
    returned = risk_gate.apply(decision, st)
    assert returned is decision
    assert decision.hard_veto is True
    assert decision.tradable is False


async def test_gate_apply_does_not_veto_hold() -> None:
    decision = SPKDecision(action="HOLD")
    risk_gate.apply(decision, state())
    assert decision.hard_veto is False
