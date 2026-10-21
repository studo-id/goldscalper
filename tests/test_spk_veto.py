from datetime import datetime, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

from agents.base import AgentSignal
from agents.state import VETO_ALL, VETO_BUY, VETO_SELL, SharedState
from spk.decision import ACTION_BUY, ACTION_SELL
from spk.veto import VetoParams, evaluate


def _veto_sig(flag: str, agent_id: str = "Risk-DrawdownGuard", division: str | None = None) -> AgentSignal:
    div = division or ("timeframe" if agent_id.startswith("TF-") else "risk")
    return AgentSignal(agent_id=agent_id, division=div, vote=0, confidence=1.0, veto=flag)


def test_hard_veto_blocks_matching_direction() -> None:
    result = evaluate([_veto_sig(VETO_BUY)], SharedState(), ACTION_BUY)
    assert result.hard is True
    assert "blocked" in (result.reason or "")


def test_htf_macro_veto_is_soft_penalty_not_hard_block() -> None:
    # H1/D1 macro timeframe agent issues directional veto:
    # Must NOT hard-block ultra-fast M1 scalper; instead softens to confidence penalty!
    h1_sig = AgentSignal(agent_id="TF-H1-Regime", division="timeframe", vote=0, confidence=0.80, veto=VETO_SELL)
    result = evaluate([h1_sig], SharedState(), ACTION_SELL)
    assert result.hard is False
    assert result.confidence_delta < 0.0
    assert any("softened" in n.lower() for n in result.notes)


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

def test_extreme_valuation_boundary_hard_veto() -> None:
    # When d1_macro_hard_veto_enabled=True, EXTREME_DISCOUNT remains a hard veto
    sig = AgentSignal(
        agent_id="TF-D1-Macro",
        division="timeframe",
        vote=0,
        confidence=0.8,
        veto=VETO_SELL,
        reasoning="Market is at EXTREME_DISCOUNT support boundary",
    )
    state = SharedState(extra={"market_regime": "SIDEWAY"})
    result = evaluate([sig], state, ACTION_SELL, params=VetoParams(d1_macro_hard_veto_enabled=True))
    assert result.hard is True
    assert "EXTREME BOUNDARY" in (result.reason or "")


def test_d1_macro_extreme_discount_softened_by_default() -> None:
    # For agile scalping, TF-D1-Macro is softened to confidence penalty, not hard veto
    sig = AgentSignal(
        agent_id="TF-D1-Macro",
        division="timeframe",
        vote=0,
        confidence=0.8,
        veto=VETO_SELL,
        reasoning="D1 macro BEARISH zone EXTREME_DISCOUNT",
    )
    state = SharedState(extra={"market_regime": "SIDEWAY"})
    # Default params: d1_macro_hard_veto_enabled=False
    result = evaluate([sig], state, ACTION_SELL)
    assert result.hard is False
    assert result.confidence_delta == -0.15
    assert any("D1 Macro valuation softened" in n for n in result.notes)

    # When explicitly configured with d1_macro_hard_veto_enabled=True:
    p_hard = VetoParams(d1_macro_hard_veto_enabled=True)
    result_hard = evaluate([sig], state, ACTION_SELL, params=p_hard)
    assert result_hard.hard is True


def test_sr_barrier_demoted_by_spk_consensus_in_defense_mode() -> None:
    # S/R barrier agent issues VETO_BUY with high confidence
    barrier_sig = AgentSignal(
        agent_id="Tech-SupportResistance",
        division="technical",
        vote=-1,
        confidence=0.80,
        veto=VETO_BUY,
        reasoning="price in M1 upper resistance zone ($4136.12), veto BUY",
    )
    # 6 confirming BUY voters vs 1 opposing
    confirming = [
        AgentSignal(agent_id=f"buy_{i}", division="trend", vote=1, confidence=0.7)
        for i in range(6)
    ]
    signals = [barrier_sig] + confirming
    state = SharedState(daily_pnl_pct=-4.0)

    result = evaluate(signals, state, ACTION_BUY)
    assert result.hard is False
    assert result.confidence_delta < 0.0
    assert any("demoted to soft penalty" in n for n in result.notes)


def test_sr_barrier_retained_near_finish_line() -> None:
    # Near finish line (remaining <= $20), S/R barrier remains a strict hard veto
    barrier_sig = AgentSignal(
        agent_id="Tech-SupportResistance",
        division="technical",
        vote=-1,
        confidence=0.80,
        veto=VETO_BUY,
        reasoning="price in M1 upper resistance zone ($4136.12), veto BUY",
    )
    confirming = [
        AgentSignal(agent_id=f"buy_{i}", division="trend", vote=1, confidence=0.7)
        for i in range(6)
    ]
    signals = [barrier_sig] + confirming
    state = SharedState(extra={"remaining_target_usd": 15.0})

    result = evaluate(signals, state, ACTION_BUY)
    assert result.hard is True
    assert "FINISH_LINE_LOCKDOWN" in (result.reason or "")


def test_anti_sideway_trap_blocks_sell_at_support_floor() -> None:
    # In SIDEWAY regime, selling at the bottom (support floor) is blocked as a hard barrier
    barrier_sig = AgentSignal(
        agent_id="Tech-SupportResistance",
        division="technical",
        vote=1,
        confidence=0.80,
        veto=VETO_SELL,
        reasoning="price in M1 lower support zone ($4130.48), veto SELL",
    )
    # Even if 6 trend agents vote SELL into the floor
    confirming_sell = [
        AgentSignal(agent_id=f"sell_{i}", division="trend", vote=-1, confidence=0.7)
        for i in range(6)
    ]
    signals = [barrier_sig] + confirming_sell
    state = SharedState(extra={"market_regime": "SIDEWAY"})

    result = evaluate(signals, state, ACTION_SELL)
    assert result.hard is True
    assert "ANTI_SIDEWAY_TRAP" in (result.reason or "")
    assert "SUPPORT FLOOR" in (result.reason or "")


def test_anti_sideway_trap_allows_m1_sniper_scalp() -> None:
    # When TF-M1-Sniper detects a fast scalping trigger, sideway trap is demoted to soft penalty
    barrier_sig = AgentSignal(
        agent_id="Tech-SupportResistance",
        division="technical",
        vote=1,
        confidence=0.80,
        veto=VETO_SELL,
        reasoning="price in M1 lower support zone ($4130.48), veto SELL",
    )
    sniper_sig = AgentSignal(
        agent_id="TF-M1-Sniper",
        division="timeframe",
        vote=-1,
        confidence=0.60,
        reasoning="bearish body (sniper)",
    )
    signals = [barrier_sig, sniper_sig]
    state = SharedState(extra={"market_regime": "SIDEWAY"})

    result = evaluate(signals, state, ACTION_SELL)
    assert result.hard is False
    assert result.confidence_delta == -0.10
    assert any("demoted to soft penalty" in note for note in result.notes)


def test_anti_sideway_trap_allows_waterfall_and_multi_division_breakout() -> None:
    # When market undergoes a multi-division waterfall crash, sideway trap must demote
    barrier_sig = AgentSignal(
        agent_id="Tech-SupportResistance",
        division="technical",
        vote=1,
        confidence=0.80,
        veto=VETO_SELL,
        reasoning="sideway bounce at support ($4112.4), veto SELL",
    )
    session_sig = AgentSignal(
        agent_id="Struct-Session",
        division="structure",
        vote=-1,
        confidence=0.85,
        reasoning="TOKYO waterfall crash (-$9.9 from open), veto BUY",
    )
    trend_sig = AgentSignal(
        agent_id="Tech-Trend",
        division="technical",
        vote=-1,
        confidence=0.70,
        reasoning="EMA downtrend",
    )
    macro_sig = AgentSignal(
        agent_id="Fund-MacroRegime",
        division="fundamental",
        vote=-1,
        confidence=0.60,
        reasoning="hawkish stance",
    )
    m5_sig = AgentSignal(
        agent_id="TF-M5-Inspector",
        division="timeframe",
        vote=-1,
        confidence=0.60,
        reasoning="bearish M5 setup",
    )
    signals = [barrier_sig, session_sig, trend_sig, macro_sig, m5_sig]
    state = SharedState(extra={"market_regime": "SIDEWAY", "sideways_range": True})

    result = evaluate(signals, state, ACTION_SELL)
    assert result.hard is False
    assert result.confidence_delta == -0.10
    assert any("demoted to soft penalty" in note for note in result.notes)




def test_counter_trend_defense_blocks_buy_during_h1_d1_downtrend() -> None:
    # During confirmed H1 and D1 downtrend in Defense mode, counter-trend BUY is blocked
    h1_sig = AgentSignal(
        agent_id="TF-H1-Regime",
        division="timeframe",
        vote=-1,
        confidence=0.80,
        veto=VETO_BUY,
        reasoning="H1 regime TRENDING bias BEARISH (VETO_BUY)",
    )
    d1_sig = AgentSignal(
        agent_id="TF-D1-Macro",
        division="timeframe",
        vote=-1,
        confidence=0.80,
        veto=VETO_BUY,
        reasoning="D1 macro BEARISH zone DISCOUNT (VETO_BUY)",
    )
    # A few micro M1 agents trying to buy a bounce
    m1_buy = [
        AgentSignal(agent_id=f"m1_buy_{i}", division="technical", vote=1, confidence=0.6)
        for i in range(3)
    ]
    signals = [h1_sig, d1_sig] + m1_buy
    state = SharedState(daily_pnl_pct=-3.0)

    # 1. When counter_trend_defense_block_enabled is True, BUY is strictly blocked
    result_buy = evaluate(signals, state, ACTION_BUY, params=VetoParams(counter_trend_defense_block_enabled=True))
    assert result_buy.hard is True
    assert "COUNTER_TREND_DEFENSE" in (result_buy.reason or "")

    # 2. When disabled (default for M1 scalper), BUY is softened to confidence penalty
    result_soft = evaluate(signals, state, ACTION_BUY)
    assert result_soft.hard is False
    assert result_soft.confidence_delta < 0.0

    # 3. But SELL with the trend is completely allowed!
    result_sell = evaluate(signals, state, ACTION_SELL)
    assert result_sell.hard is False





