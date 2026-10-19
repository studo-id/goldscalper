from datetime import datetime, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

from agents.base import AgentSignal
from agents.state import VETO_ALL, VETO_BUY, VETO_SELL, SharedState
from spk.decision import ACTION_BUY, ACTION_SELL
from spk.veto import VetoParams, evaluate


def _veto_sig(flag: str, agent_id: str = "TF-H1-Regime") -> AgentSignal:
    return AgentSignal(agent_id=agent_id, division="timeframe", vote=0, confidence=1.0, veto=flag)


def test_hard_veto_blocks_matching_direction() -> None:
    result = evaluate([_veto_sig(VETO_BUY)], SharedState(), ACTION_BUY)
    assert result.hard is True
    assert "blocked" in (result.reason or "")


def test_veto_all_blocks_both_buy_and_sell() -> None:
    sig = AgentSignal(agent_id="Tech-SupportResistance", division="technical", vote=0, confidence=0.85, veto=VETO_ALL, reasoning="mid dead zone")
    res_buy = evaluate([sig], SharedState(), ACTION_BUY)
    assert res_buy.hard is True
    assert "blocked trade in M1 mid-range dead zone" in (res_buy.reason or "")

    res_sell = evaluate([sig], SharedState(), ACTION_SELL)
    assert res_sell.hard is True
    assert "blocked trade in M1 mid-range dead zone" in (res_sell.reason or "")


def test_veto_does_not_affect_opposite_direction() -> None:
    result = evaluate([_veto_sig(VETO_BUY)], SharedState(), ACTION_SELL)
    assert result.hard is False


def test_sell_veto_blocks_sell() -> None:
    result = evaluate([_veto_sig(VETO_SELL)], SharedState(), ACTION_SELL)
    assert result.hard is True


def test_daily_loss_limit_hard_veto() -> None:
    state = SharedState(daily_loss_exceeded=True)
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is True
    assert "daily loss" in (result.reason or "")


def test_weekly_loss_limit_hard_veto() -> None:
    result = evaluate([], SharedState(weekly_loss_exceeded=True), ACTION_BUY)
    assert result.hard is True


def test_news_blackout_hard_veto() -> None:
    state = SharedState(extra={"news_blackout": True})
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is True
    assert "news" in (result.reason or "")


def test_d1_extreme_zone_hard_veto() -> None:
    state = SharedState(extra={"d1_extreme_zone": True})
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is True


def test_h4_block_touch_hard_veto() -> None:
    state = SharedState(extra={"h4_block_touch": True})
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is True


def test_soft_vetoes_accumulate() -> None:
    state = SharedState(
        spread_points=100,
        session="asia",
        extra={"h1_vote": -1},
    )
    result = evaluate([], state, ACTION_BUY, VetoParams(max_spread_points=45))
    assert result.hard is False
    # htf 0.30 + spread 0.20 + low liquidity 0.15 = 0.65
    assert abs(result.confidence_delta - (-0.65)) < 1e-6
    assert len(result.notes) == 3


def test_no_veto_clean_state() -> None:
    state = SharedState(spread_points=10, session="london", extra={"h1_vote": 1})
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is False
    assert result.confidence_delta == 0.0
    assert result.notes == []


def test_htf_deadlock_demotes_to_soft_veto() -> None:
    # Both VETO_BUY and VETO_SELL present from timeframe division
    signals = [
        _veto_sig(VETO_BUY, "TF-D1-Macro"),
        _veto_sig(VETO_SELL, "TF-H1-Regime"),
    ]
    result = evaluate(signals, SharedState(), ACTION_BUY)
    assert result.hard is False
    assert result.confidence_delta < 0.0
    assert any("deadlock" in n.lower() or "demoted" in n.lower() for n in result.notes)


def test_ping_pong_sideways_bypasses_htf_veto() -> None:
    # Pattern agent has ping_pong_side == BUY at support
    pp_sig = AgentSignal(
        agent_id="Tech-Pattern",
        division="technical",
        vote=1,
        confidence=0.80,
        metadata={"ping_pong_side": "BUY"},
    )
    htf_sig = _veto_sig(VETO_BUY, "TF-D1-Macro")
    result = evaluate([pp_sig, htf_sig], SharedState(), ACTION_BUY)
    assert result.hard is False
    assert any("demoted" in n.lower() for n in result.notes)


def test_sideway_gate_vetoes_buy_above_midline() -> None:
    state = SharedState(
        bid=2360.0,
        extra={"sideways_range": True, "sr_midline": 2355.0, "sr_support": 2350.0, "sr_resistance": 2360.0},
    )
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is False
    assert result.confidence_delta < 0
    assert any("resistance ceiling caution" in n.lower() for n in result.notes)


def test_sideway_gate_vetoes_sell_below_midline() -> None:
    state = SharedState(
        bid=2350.0,
        extra={"sideways_range": True, "sr_midline": 2355.0, "sr_support": 2350.0, "sr_resistance": 2360.0},
    )
    result = evaluate([], state, ACTION_SELL)
    assert result.hard is False
    assert result.confidence_delta < 0
    assert any("support floor caution" in n.lower() for n in result.notes)


def test_sideway_gate_allows_buy_below_midline() -> None:
    state = SharedState(
        bid=2352.0,
        extra={"sideways_range": True, "sr_midline": 2355.0, "sr_support": 2350.0, "sr_resistance": 2360.0},
    )
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is False


def test_hard_barrier_sr_rejection_cannot_be_softened() -> None:
    # High-confidence resistance rejection must NOT be demoted even during sideways / deadlock
    sig = AgentSignal(
        agent_id="Tech-SupportResistance",
        division="technical",
        vote=-1,
        confidence=0.80,
        veto=VETO_BUY,
        reasoning="sideway rejection at resistance ($4159.1), veto BUY",
    )
    state = SharedState(extra={"sideways_range": True})
    result = evaluate([sig], state, ACTION_BUY)
    assert result.hard is True
    assert "HARD BARRIER" in (result.reason or "")
    assert state.extra.get("active_sr_barrier") == "RESISTANCE"


def test_daily_profit_locked_hard_veto() -> None:
    state = SharedState(daily_profit_locked=True)
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is True
    assert "daily profit target locked" in (result.reason or "")


def test_daily_sprint_profit_target_reached_hard_veto() -> None:
    state = SharedState(
        daily_realized_pnl=50.0,
        extra={"remaining_target_usd": 0.0, "target_usd": 40.0},
    )
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is True
    assert "target achieved" in (result.reason or "")


def test_drawdown_amplifies_soft_veto_penalties() -> None:
    # In drawdown (-6.0%), pnl_penalty_mult is 1.0 + 6.0/12.0 = 1.5x
    state = SharedState(
        daily_pnl_pct=-6.0,
        spread_points=100,  # wide spread > 45
        session="asia",     # low liquidity
        extra={"h1_vote": -1},  # HTF conflict
    )
    result = evaluate([], state, ACTION_BUY, VetoParams(max_spread_points=45))
    assert result.hard is False
    # Normally base penalty = 0.30 + 0.20 + 0.15 = 0.65
    # With 1.5x scaling = 0.45 + 0.30 + 0.225 = 0.975 (capped/rounded)
    assert result.confidence_delta < -0.80


def test_finish_line_spread_caution() -> None:
    state = SharedState(
        spread_points=38,  # Below max_spread 45, but > 45 * 0.75 = 33.75
        extra={"remaining_target_usd": 10.0},
    )
    result = evaluate([], state, ACTION_BUY, VetoParams(max_spread_points=45))
    assert any("finish line spread caution" in n for n in result.notes)


def test_tick_feed_stale_hard_veto() -> None:
    state = SharedState(extra={"last_tick_age_s": 8.5})
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is True
    assert "tick feed stale" in (result.reason or "")


def test_mt5_bridge_disconnected_hard_veto() -> None:
    state = SharedState(extra={"mt5_connected": False})
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is True
    assert "MT5 bridge disconnected" in (result.reason or "")


def test_london_open_freeze_hard_veto() -> None:
    # Triggered via extra flag from runtime
    state = SharedState(extra={"london_open_freeze": True})
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is True
    assert "LONDON_OPEN_OBSERVATION" in (result.reason or "")


def test_london_open_allowed_after_freeze() -> None:
    # When freeze flag is False, hard veto is not raised
    state = SharedState(extra={"london_open_freeze": False})
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is False


def test_session_hard_cutoff_1530_utc() -> None:
    # Triggered via extra flag from runtime
    state = SharedState(extra={"session_hard_cutoff": True})
    result = evaluate([], state, ACTION_BUY)
    assert result.hard is True
    assert "SESSION_HARD_CUTOFF_1530_UTC" in (result.reason or "")






