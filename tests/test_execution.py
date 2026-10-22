"""Tests for the execution layer (mock MT5)."""

from __future__ import annotations

from datetime import datetime, timedelta

from agents.base import AgentSignal
from agents.state import UTC, SharedState, utcnow
from config.settings import settings
from core.mt5_connector import SIDE_BUY, SIDE_SELL, MockMT5Client, OrderRequest, Position
from core.notifier import Notifier
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from spk.decision import ACTION_BUY, ACTION_SELL, STRENGTH_STRONG, SPKDecision


class FakeTradeRepo:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def open_trade(self, fields: dict) -> str:
        self.rows.append(fields)
        return "trade-1"


def _decision(**kw: object) -> SPKDecision:
    base: dict = {
        "action": ACTION_BUY,
        "strength": STRENGTH_STRONG,
        "score": 3.0,
        "confidence": 0.8,
        "size": 0.20,
        "sl": 2340.0,
        "tp": 2360.0,
        "entry": 2350.0,
    }
    base.update(kw)
    return SPKDecision(**base)


# --- order manager -------------------------------------------------------------


async def test_order_manager_skips_hold() -> None:
    om = OrderManager(client=MockMT5Client(), settings=settings)
    assert await om.execute(_decision(action="HOLD", size=0.0)) is None


async def test_order_manager_skips_zero_size() -> None:
    om = OrderManager(client=MockMT5Client(), settings=settings)
    result = await om.execute(_decision(size=0.0))
    assert result is not None
    assert result.ok is False
    assert result.reason == "zero size"


async def test_order_manager_executes_and_records() -> None:
    client = MockMT5Client()
    repo = FakeTradeRepo()
    om = OrderManager(client=client, settings=settings, trade_repo=repo)
    result = await om.execute(_decision())
    assert result is not None and result.ok
    assert result.ticket is not None
    assert result.trade_id == "trade-1"
    assert len(repo.rows) == 1
    assert repo.rows[0]["direction"] == "BUY"
    positions = await client.positions(settings.mt5_symbol)
    assert len(positions) == 1
    assert positions[0].sl == 2340.0
    assert positions[0].tp == 2360.0


async def test_order_manager_respects_max_positions() -> None:
    from config.settings import Settings
    client = MockMT5Client()
    custom = Settings(max_open_positions=1)
    om = OrderManager(client=client, settings=custom)
    first = await om.execute(_decision())
    assert first is not None and first.ok
    second = await om.execute(_decision())
    assert second is not None
    assert second.ok is False
    assert second.reason == "max open positions"


class _EnabledNotifier(Notifier):
    @property
    def enabled(self) -> bool:
        return True

    async def send(self, text: str, *, parse_mode: str | None = "HTML") -> bool:
        return True


async def test_order_manager_smart_rescue_multiplier() -> None:
    from config.settings import Settings
    client = MockMT5Client()
    custom = Settings(rescue_multiplier=1.35, rescue_min_distance_pips=10.0)
    om = OrderManager(client=client, settings=custom)
    first = await om.execute(_decision(entry=2350.0, size=0.20))
    assert first is not None and first.ok
    assert first.size == 0.20

    # Second entry is lower than 2350 -> triggers Rescue Recovery Layer 2
    second = await om.execute(_decision(entry=2348.0, size=0.20))
    assert second is not None and second.ok
    # 0.20 * 1.35 = 0.27 lot!
    assert second.size == 0.27


async def test_order_manager_notifies() -> None:
    notifier = _EnabledNotifier()
    om = OrderManager(client=MockMT5Client(), settings=settings, notifier=notifier)
    result = await om.execute(_decision())
    assert result is not None and result.ok


async def test_order_manager_blocks_multi_entry_near_finish_line() -> None:
    from agents.state import SharedState
    client = MockMT5Client()
    om = OrderManager(client=client, settings=settings)
    # Open initial position
    await om.execute(_decision(entry=2350.0))
    # Second trade attempted when remaining target is <= $20
    state = SharedState(extra={"remaining_target_usd": 15.0})
    result = await om.execute(_decision(entry=2345.0), state=state)
    assert result is not None
    assert result.ok is False
    assert "finish line proximity" in (result.reason or "")


async def test_order_manager_blocks_pyramid_during_drawdown() -> None:
    from agents.state import SharedState
    client = MockMT5Client()
    om = OrderManager(client=client, settings=settings)
    # Open initial BUY position at 2350
    await om.execute(_decision(entry=2350.0))
    # Move mock client price higher to 2355 so initial position has floating profit
    client._price = 2355.0
    # Attempt pyramid BUY at 2355 (higher than 2350) while in drawdown (-3.0%)
    state = SharedState(daily_pnl_pct=-3.0)
    result = await om.execute(_decision(entry=2355.0), state=state)
    assert result is not None
    assert result.ok is False
    assert "drawdown pyramid" in (result.reason or "")



# --- position manager ----------------------------------------------------------


async def _open_position(client: MockMT5Client, sl: float, volume: float = 1.0):
    await client.order_send(
        OrderRequest(
            symbol="XAUUSD",
            side=SIDE_BUY,
            volume=volume,
            sl=sl,
            tp=sl + 100,
            magic=settings.mt5_magic,
        )
    )
    return (await client.positions("XAUUSD"))[0]


async def test_position_manager_breakeven_and_partial() -> None:
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)
    pos_sl = pos_sl_fn()
    pos = await _open_position(client, sl=pos_sl)
    entry = pos.price_open
    r = abs(entry - pos_sl)
    actions = await pm.manage(pos, entry + 1.05 * r)
    assert "breakeven" in actions
    assert "partial_tp" in actions
    refreshed = (await client.positions("XAUUSD"))[0]
    assert refreshed.sl >= entry
    assert refreshed.volume < 1.0


async def test_position_manager_stagnant_harvest() -> None:
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)
    pos = await _open_position(client, sl=pos_sl_fn())
    pos.profit = 2.50  # floating profit above stagnant_min_profit_usd
    future = utcnow() + timedelta(seconds=settings.stagnant_harvest_seconds + 5)
    actions = await pm.manage(pos, pos.price_open + 0.50, now=future)
    assert "stagnant_harvest" in actions
    assert await client.positions("XAUUSD") == []


async def test_position_manager_time_stop() -> None:
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)
    pos = await _open_position(client, sl=pos_sl_fn())
    future = utcnow() + timedelta(seconds=settings.max_hold_seconds + 10)
    actions = await pm.manage(pos, pos.price_open, now=future)
    assert actions == ["time_stop"]
    assert await client.positions("XAUUSD") == []


def pos_sl_fn() -> float:
    # A fixed reference stop; the actual fill is near 2350 so 1R ~ 10.
    return 2340.0


async def test_position_manager_no_r_no_action() -> None:
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)
    pos = await _open_position(client, sl=pos_sl_fn())
    pos.sl = None
    actions = await pm.manage(pos, pos.price_open)
    assert actions == []


async def test_position_manager_manage_basket_pyramid_protects_runners() -> None:
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)
    now = utcnow()
    # Layer 1 entered at 2350, Layer 2 entered higher at 2352 (pyramiding in profit)
    pos1 = Position(ticket=101, symbol="XAUUSD", side=SIDE_BUY, volume=0.01, price_open=2350.0, price_current=2352.5, profit=2.5, time=now - timedelta(seconds=60))
    pos2 = Position(ticket=102, symbol="XAUUSD", side=SIDE_BUY, volume=0.01, price_open=2352.0, price_current=2352.5, profit=0.5, time=now)
    
    # Even though price 2352.5 > avg_entry 2351.0 + buffer, total profit is $3.0 < $7.50 pyramid runner target
    actions = await pm.manage_basket([pos1, pos2], current_bid=2352.5, current_ask=2352.7)
    assert actions == []  # Pyramid runners are protected!

    # When total profit reaches runner target >= $7.50 without trailing delay:
    pm.settings.basket_trailing_enabled = False
    pos1.profit = 5.5
    pos2.profit = 2.5
    actions_harvest = await pm.manage_basket([pos1, pos2], current_bid=2355.0, current_ask=2355.2)
    assert any("basket_tp" in a for a in actions_harvest)


async def test_position_manager_overnight_flat_cutoff() -> None:
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)
    open_time = datetime(2026, 1, 5, 21, 0, tzinfo=UTC)
    now_2105 = datetime(2026, 1, 5, 21, 5, tzinfo=UTC)
    pos = Position(ticket=201, symbol="XAUUSD", side=SIDE_BUY, volume=0.01, price_open=2350.0, price_current=2351.0, profit=1.0, time=open_time)
    
    actions = await pm.manage(pos, price=2351.0, now=now_2105)
    assert "overnight_flat_cutoff" in actions
    assert await client.positions() == []

    # But at 22:05 UTC (Asia session open on Tuesday morning), it must NOT cut off!
    client2 = MockMT5Client()
    pm2 = PositionManager(client=client2, settings=settings)
    now_2205 = datetime(2026, 1, 5, 22, 5, tzinfo=UTC)
    pos2 = Position(ticket=202, symbol="XAUUSD", side=SIDE_BUY, volume=0.01, price_open=2350.0, price_current=2351.0, profit=1.0, time=now_2205)
    actions2 = await pm2.manage(pos2, price=2351.0, now=now_2205)
    assert "overnight_flat_cutoff" not in actions2


async def test_risk_gate_blocks_during_overnight_flat_window() -> None:
    from agents.state import SharedState
    from execution.risk_gate import evaluate
    from spk.decision import ACTION_BUY, SPKDecision

    class MockSizerVote:
        agent_id = "Risk-PositionSizer"
        metadata = {"size": 0.10, "sizing_mode": "TARGET_SEEKING"}

    dec = SPKDecision(action=ACTION_BUY, score=3.0, confidence=0.7, votes=[MockSizerVote()])
    state_rollover = SharedState(symbol="XAUUSD", ts=datetime(2026, 1, 5, 21, 15, tzinfo=UTC))
    res_rollover = evaluate(dec, state_rollover, settings=settings)
    assert res_rollover.approved is False
    assert "overnight flat cutoff" in (res_rollover.reason or "")

    # But during Asia open (22:05 UTC), risk gate allows evaluation through
    state_asia = SharedState(symbol="XAUUSD", ts=datetime(2026, 1, 5, 22, 5, tzinfo=UTC), bid=2350.0, ask=2350.2)
    res_asia = evaluate(dec, state_asia, settings=settings)
    assert res_asia.approved is True


async def test_notifier_disabled_is_noop() -> None:
    notifier = Notifier()
    assert notifier.enabled is False
    assert await notifier.send("hello") is False
    assert await notifier.alert("danger") is False
    assert notifier.sent == 0


async def test_watchdog_time_extension_and_invalidation_cut() -> None:
    from agents.base import AgentSignal
    from spk.decision import ACTION_BUY, SPKDecision

    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)
    now = utcnow()
    pos = await _open_position(client, sl=2335.0, volume=0.10)
    pos.time = now - timedelta(seconds=settings.max_hold_seconds + 30)

    # 1. When HTF is supporting and M5 is not opposing -> Time Extension granted!
    supporting_signals = [
        AgentSignal(agent_id="TF-H4-Structure", division="timeframe", vote=1, confidence=0.8),
        AgentSignal(agent_id="TF-H1-Regime", division="timeframe", vote=1, confidence=0.8),
        AgentSignal(agent_id="TF-M5-Inspector", division="timeframe", vote=0, confidence=0.5),
    ]
    dec_supp = SPKDecision(action=ACTION_BUY, score=4.0, confidence=0.8, votes=supporting_signals)
    actions = await pm.manage(pos, price=2349.5, now=now, context={"decision": dec_supp})
    assert "time_stop" not in actions  # Extended!

    # 2. When M1 and M5 both oppose our position:
    adverse_signals = [
        AgentSignal(agent_id="TF-M1-Sniper", division="timeframe", vote=-1, confidence=0.8),
        AgentSignal(agent_id="TF-M5-Inspector", division="timeframe", vote=-1, confidence=0.7),
    ]
    dec_adv = SPKDecision(action=ACTION_BUY, score=-3.0, confidence=0.8, votes=adverse_signals)
    pos.profit = -7.00  # floating loss exceeding early threshold ($7.00 >= $6.40)

    # 2a. Under 60s (e.g. 35s): Intra-candle M1 wick grace period PROTECTS the position even at -$9.00!
    pos.profit = -9.00
    pm._states[pos.ticket].opened_at = now - timedelta(seconds=35)
    actions_wick = await pm.manage(pos, price=2349.5, now=now, context={"decision": dec_adv})
    assert "watchdog_early_invalidation_cut" not in actions_wick
    assert "juggler_dynamic_clamp" not in actions_wick
    assert len(await client.positions("XAUUSD")) == 1

    # 2a-gap. Under 60s with catastrophic loss (>= 45-50 pips, e.g. -$50.00 on 0.10 lot): triggers catastrophic cut!
    pos.profit = -50.00
    actions_cat = await pm.manage(pos, price=2349.5, now=now, context={"decision": dec_adv})
    assert "juggler_catastrophic_gap_cut" in actions_cat
    assert await client.positions("XAUUSD") == []

    # Re-open position for subsequent 65s tests
    pos = await _open_position(client, sl=2335.0, volume=0.10)
    pm.track(pos)

    # 2b. At 65s (held >= 60s), if M1 opposes but M5 is SUPPORTING: DO NOT CUT — Hold for M5 Reversal!
    m5_supp_signals = [
        AgentSignal(agent_id="TF-M1-Sniper", division="timeframe", vote=-1, confidence=0.8),
        AgentSignal(agent_id="TF-M5-Inspector", division="timeframe", vote=1, confidence=0.7),
    ]
    dec_m5_supp = SPKDecision(action=ACTION_BUY, score=0.0, confidence=0.7, votes=m5_supp_signals)
    pm._states[pos.ticket].opened_at = now - timedelta(seconds=65)
    pos.profit = -5.00
    actions_hold = await pm.manage(pos, price=2349.5, now=now, context={"decision": dec_m5_supp})
    assert "watchdog_early_invalidation_cut" not in actions_hold
    assert len(await client.positions("XAUUSD")) == 1

    # 2c. Only once M5 also confirms OPPOSING (both M1 & M5 oppose): Early Invalidation Cut triggers!
    pm._states[pos.ticket].opened_at = now - timedelta(seconds=65)
    pos.profit = -5.00
    actions_cut = await pm.manage(pos, price=2349.5, now=now, context={"decision": dec_adv})
    assert "watchdog_early_invalidation_cut" in actions_cut
    assert await client.positions("XAUUSD") == []


async def test_fast_breakeven_lock() -> None:
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)
    now = utcnow()
    pos = await _open_position(client, sl=2340.0, volume=0.01)
    pos.profit = 2.50  # +25 pips on 0.01 lot = $2.50 >= be_trigger_usd $1.20

    actions = await pm.manage(pos, price=2350.25, now=now)
    assert "breakeven_locked" in actions
    refreshed = (await client.positions("XAUUSD"))[0]
    assert refreshed.sl == round(pos.price_open + 0.10, 2)  # Locked into entry + 0.10


async def test_htf_reversal_shield_protects_minor_pullback() -> None:
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)
    now = utcnow()
    pos = await _open_position(client, sl=2335.0, volume=0.08)
    pm.track(pos)

    # Position held 65s (> 60s min_hold), floating loss is -$11.50 (exceeds $7.00 clamp)
    pm._states[pos.ticket].opened_at = now - timedelta(seconds=65)
    pos.profit = -11.50

    # HTF (H1, H4, M30) is strongly supporting the trade
    htf_supporting_signals = [
        AgentSignal(agent_id="TF-H1-Regime", division="timeframe", vote=1, confidence=0.8),
        AgentSignal(agent_id="TF-H4-Structure", division="timeframe", vote=1, confidence=0.8),
    ]
    dec = SPKDecision(action=ACTION_BUY, score=3.0, confidence=0.8, votes=htf_supporting_signals)

    actions = await pm.manage(pos, price=2349.5, now=now, context={"decision": dec})
    # HTF Reversal Shield protects the position from premature $7.00 clamp cut!
    assert "juggler_dynamic_clamp" not in actions
    assert len(await client.positions("XAUUSD")) == 1

    # But if loss reaches extreme / catastrophic clamp level (> $28.00 for 0.08 lot, e.g. -$29.50), clamp triggers
    pos.profit = -29.50
    actions_deep = await pm.manage(pos, price=2349.5, now=now, context={"decision": dec})
    assert "juggler_dynamic_clamp" in actions_deep
    assert await client.positions("XAUUSD") == []


async def test_rescue_basket_bypasses_individual_clamp_and_bep() -> None:
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)
    now = utcnow()
    pos = await _open_position(client, sl=2335.0, volume=0.08)
    pm.track(pos)
    # Position held 125s in active rescue basket with adverse move -$6.79
    pm._states[pos.ticket].opened_at = now - timedelta(seconds=125)
    pos.profit = -6.79

    # In rescue basket: duration loss cut (Phase 4) and dynamic clamp (Phase 3) are completely bypassed!
    actions = await pm.manage(pos, price=2349.5, now=now, context={"in_rescue_basket": True})
    assert actions == []
    assert len(await client.positions("XAUUSD")) == 1

    # In rescue basket: individual runner harvest and BEP lock are also bypassed to preserve basket unity
    pos.profit = 8.02
    actions_tp = await pm.manage(pos, price=2350.5, now=now, context={"in_rescue_basket": True})
    assert actions_tp == []
    assert len(await client.positions("XAUUSD")) == 1

    # But when manage_basket runs on the full collective basket, fast salvage unlocks profit together!
    pos1 = Position(ticket=101, symbol="XAUUSD", side=SIDE_SELL, volume=0.04, price_open=4107.45, price_current=4108.45, profit=-4.00, time=now - timedelta(seconds=125))
    pos2 = Position(ticket=102, symbol="XAUUSD", side=SIDE_SELL, volume=0.04, price_open=4110.46, price_current=4108.45, profit=8.02, time=now - timedelta(seconds=64))
    pm.settings.basket_trailing_enabled = False
    basket_act = await pm.manage_basket([pos1, pos2], current_bid=4108.45, current_ask=4108.55)
    assert "basket_tp_closed" in basket_act
    assert pos1.ticket not in pm._states
    assert pos2.ticket not in pm._states


async def test_instant_runner_harvest_at_any_time() -> None:
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)
    now = utcnow()
    pos = await _open_position(client, sl=2335.0, volume=0.06)
    pm.track(pos)

    # Position held only 45s (< 90s), but market plunges delivering +$12.50 runner profit
    pm._states[pos.ticket].opened_at = now - timedelta(seconds=45)
    pos.profit = 12.50

    actions = await pm.manage(pos, price=2348.0, now=now)
    # Runner harvest executes immediately without waiting for 90s!
    assert "juggler_runner_harvest" in actions
    assert await client.positions("XAUUSD") == []


async def test_dynamic_data_driven_sr_boundary_gate() -> None:
    client = MockMT5Client()
    om = OrderManager(client=client, settings=settings)

    # Mock M5 candles forming a range between 4115.0 and 4125.0
    mock_m5 = []
    for i in range(10):
        mock_m5.append({
            "open": 4120.0,
            "high": 4125.0,
            "low": 4115.0,
            "close": 4121.0,
        })
    state = SharedState(
        symbol="XAUUSDm",
        frames={"M5": mock_m5},
        extra={"market_regime": "SIDEWAY", "struct_event": "RANGE"},
    )

    # 1. Buying right near resistance (4124.90, dist=0.10) without confirmed breakout MUST be blocked by data
    dec_buy_top = SPKDecision(action=ACTION_BUY, score=2.5, confidence=0.7, size=0.08, entry=4124.90)
    res_buy = await om.execute(dec_buy_top, state=state)
    assert res_buy is not None and not res_buy.ok
    assert "Blocked BUY near resistance ceiling" in (res_buy.reason or "")

    # 2. Selling right near support (4115.20, dist=0.20) without confirmed breakdown MUST be blocked by data
    dec_sell_bottom = SPKDecision(action=ACTION_SELL, score=-2.5, confidence=0.7, size=0.08, entry=4115.20)
    res_sell = await om.execute(dec_sell_bottom, state=state)
    assert res_sell is not None and not res_sell.ok
    assert "Blocked SELL near support floor" in (res_sell.reason or "")

    # 3. But if data shows clean breakout (last candle closed at 4126.0 > 4125.30 with HH_HL), BUY is permitted!
    mock_m5_breakout = list(mock_m5)
    mock_m5_breakout[-1] = {"open": 4124.0, "high": 4127.0, "low": 4123.0, "close": 4126.5}
    state_breakout = SharedState(
        symbol="XAUUSDm",
        frames={"M5": mock_m5_breakout},
        extra={"market_regime": "SIDEWAY", "struct_event": "HH_HL"},
    )
    res_breakout = await om.execute(dec_buy_top, state=state_breakout)
    assert res_breakout is not None and res_breakout.ok
    assert res_breakout.ticket is not None


async def test_rescue_defense_mode_spacing_and_lot_cap() -> None:
    client = MockMT5Client()
    om = OrderManager(client=client, settings=settings)
    # Defense mode: daily_pnl_pct = -2.5%
    state = SharedState(symbol="XAUUSDm", daily_pnl_pct=-2.5)
    
    # 1. Open initial trade at 2350.0 with 0.04 lot
    first = await om.execute(_decision(entry=2350.0, size=0.04), state=state)
    assert first is not None and first.ok
    assert first.size == 0.04

    # 2. Attempt rescue at 2348.1 (dist=1.90 USD = 19 pips) -> Rejected (too close, min 30 pips / $3.00 in DEFENSE mode)
    second_too_close = await om.execute(_decision(entry=2348.1, size=0.04), state=state)
    assert second_too_close is not None and not second_too_close.ok
    assert "distance too close" in (second_too_close.reason or "")

    # 3. Attempt rescue at 2346.8 (dist=3.20 USD = 32 pips >= 30 pips) -> Approved!
    # And volume MUST be capped at 0.02 lot in DEFENSE mode!
    second_ok = await om.execute(_decision(entry=2346.8, size=0.04), state=state)
    assert second_ok is not None and second_ok.ok
    assert second_ok.size == 0.02  # Defense lot conservation cap!


async def test_falling_knife_smart_momentum() -> None:
    client = MockMT5Client()
    om = OrderManager(client=client, settings=settings)

    # Initial BUY at 2350.0
    await om.execute(_decision(entry=2350.0, size=0.04))

    # Case A: 3 gentle red drift candles (total drop only 1.50 USD / 15 pips) -> ALLOWED
    gentle_reds = [
        {"open": 2348.5, "high": 2348.6, "low": 2347.9, "close": 2348.0},
        {"open": 2348.0, "high": 2348.1, "low": 2347.4, "close": 2347.5},
        {"open": 2347.5, "high": 2347.6, "low": 2346.9, "close": 2347.0},
    ]
    state_gentle = SharedState(symbol="XAUUSDm", frames={"M1": gentle_reds})
    res_gentle = await om.execute(_decision(entry=2347.0, size=0.04), state=state_gentle)
    assert res_gentle is not None and res_gentle.ok

    # Case B: 3 aggressive waterfall red candles (total drop 4.0 USD / 40 pips) -> BLOCKED
    client2 = MockMT5Client()
    om2 = OrderManager(client=client2, settings=settings)
    await om2.execute(_decision(entry=2350.0, size=0.04))
    waterfall_reds = [
        {"open": 2350.0, "high": 2350.0, "low": 2348.5, "close": 2348.5},
        {"open": 2348.5, "high": 2348.5, "low": 2347.0, "close": 2347.0},
        {"open": 2347.0, "high": 2347.0, "low": 2346.0, "close": 2346.0},
    ]
    state_waterfall = SharedState(symbol="XAUUSDm", frames={"M1": waterfall_reds})
    res_waterfall = await om2.execute(_decision(entry=2346.0, size=0.04), state=state_waterfall)
    assert res_waterfall is not None and not res_waterfall.ok
    assert "falling knife guard" in (res_waterfall.reason or "")


async def test_position_manager_m5_reversal_hold() -> None:
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)
    now = utcnow()
    pos = await _open_position(client, sl=2335.0, volume=0.04)
    pm.track(pos)
    # Held 75 seconds (past 60s noise period) with -$8.20 loss (normally cuts at -$7.00)
    pm._states[pos.ticket].opened_at = now - timedelta(seconds=75)
    pos.profit = -8.20

    # 1. When Satpam M5 is SUPPORTING, Juggler grants reversal room (held < 90s)
    actions_hold = await pm.manage(
        pos,
        price=2348.0,
        now=now,
        context={"watchdogs": {"m5": {"verdict": "SUPPORTING"}, "htf": {"verdict": "NEUTRAL"}}},
    )
    assert "juggler_dynamic_clamp" not in actions_hold
    assert len(await client.positions()) == 1

    # 2. But if Satpam M5 is OPPOSING, it is immediately cut at -$8.20
    pos.profit = -8.20  # Re-assert loss because client.positions() above mutated pos.profit
    actions_cut = await pm.manage(
        pos,
        price=2348.0,
        now=now,
        context={"watchdogs": {"m5": {"verdict": "OPPOSING"}, "htf": {"verdict": "NEUTRAL"}}},
    )
    assert "juggler_dynamic_clamp" in actions_cut
    assert len(await client.positions()) == 0


async def test_order_manager_m1_candle_cooldown() -> None:
    client = MockMT5Client()
    om = OrderManager(client=client, settings=settings)

    # Arm cooldown with post_cutloss_clamp -> must route to M1 candle cooldown (>= 60s)
    om.arm_cooldown(25, reason="post_cutloss_clamp")
    assert om.in_cooldown is True
    assert om._cooldown_m1_bucket is not None

    # New entry execution while in cooldown must be blocked
    res = await om.execute(_decision())
    assert res is not None
    assert res.ok is False
    assert "post-trade cooldown active" in (res.reason or "")


async def test_order_manager_blocks_probing_sr_boundaries() -> None:
    client = MockMT5Client()
    om = OrderManager(client=client, settings=settings)

    # M5 range: support 2345.0, resistance 2355.0, last close 2350.0 (no breakout)
    m5_bars = [
        {"open": 2350.0, "high": 2355.0, "low": 2345.0, "close": 2350.0}
        for _ in range(10)
    ]
    st = SharedState(symbol="XAUUSDm", frames={"M5": m5_bars})

    # 1. Probing at or above resistance (entry 2355.50 > 2355.0) -> BLOCKED
    res_buy = await om.execute(_decision(action=ACTION_BUY, entry=2355.50), state=st)
    assert res_buy is not None and not res_buy.ok
    assert "Blocked BUY probing above resistance ceiling" in (res_buy.reason or "")

    # 2. Probing at or below support (entry 2344.50 < 2345.0) -> BLOCKED
    res_sell = await om.execute(_decision(action=ACTION_SELL, entry=2344.50), state=st)
    assert res_sell is not None and not res_sell.ok
    assert "Blocked SELL probing below support floor" in (res_sell.reason or "")


async def test_order_manager_initial_entry_falling_knife_guard() -> None:
    """Verify that initial entry (open_count == 0) is strictly blocked during flash dump or rocket surge."""
    client = MockMT5Client()
    om = OrderManager(client=client, settings=settings)

    # 1. Initial BUY attempted while active M1 candle is an active flash dump (-$2.50 drop)
    m1_dump = [
        {"open": 2355.0, "high": 2355.2, "low": 2354.8, "close": 2355.0},
        {"open": 2355.0, "high": 2355.0, "low": 2352.4, "close": 2352.5},  # Drop $2.50, lower wick tiny
    ]
    st_dump = SharedState(symbol="XAUUSDm", frames={"M1": m1_dump})
    res_buy = await om.execute(_decision(action=ACTION_BUY, entry=2352.5), state=st_dump)
    assert res_buy is not None and not res_buy.ok
    assert "falling knife guard" in (res_buy.reason or "")

    # 2. Initial SELL attempted while active M1 candle is an active rocket pump (+$2.50 surge)
    m1_pump = [
        {"open": 2350.0, "high": 2350.2, "low": 2349.8, "close": 2350.0},
        {"open": 2350.0, "high": 2352.6, "low": 2350.0, "close": 2352.5},  # Surge $2.50, upper wick tiny
    ]
    st_pump = SharedState(symbol="XAUUSDm", frames={"M1": m1_pump})
    res_sell = await om.execute(_decision(action=ACTION_SELL, entry=2352.5), state=st_pump)
    assert res_sell is not None and not res_sell.ok
    assert "rocket surge guard" in (res_sell.reason or "")

async def test_order_manager_sr_boundary_blocks_without_confirmed_breakout() -> None:
    """Verify that BUY near/above resistance ceiling is strictly blocked without confirmed M5 breakout close."""
    client = MockMT5Client()
    om = OrderManager(client=client, settings=settings)

    st = SharedState(
        symbol="XAUUSDm",
        extra={
            "market_regime": "TRENDING_BULL",
            "sr_resistance": 4141.93,
            "sr_support": 4125.00,
            "struct_event": "HH_HL",
        },
        frames={
            "M5": [
                {"open": 4125.0, "high": 4130.0, "low": 4125.0, "close": 4129.0},
                {"open": 4129.0, "high": 4135.0, "low": 4128.0, "close": 4134.0},
                {"open": 4134.0, "high": 4138.0, "low": 4133.0, "close": 4137.0},
                {"open": 4137.0, "high": 4141.93, "low": 4136.0, "close": 4140.0},
                {"open": 4140.0, "high": 4141.5, "low": 4138.0, "close": 4139.0},  # unconfirmed close below ceiling
            ]
        },
    )

    # 1. Entry at 4139.76 (dist to res 2.17, inside 3.50 buffer) -> MUST BE BLOCKED (Ticket #4908250924 scenario)
    blocked, reason = om._check_dynamic_sr_boundary(ACTION_BUY, 4139.76, st)
    assert blocked is True
    assert "Blocked BUY near resistance ceiling" in reason

    # 2. Entry probing above resistance at 4142.10 without confirmed M5 close -> MUST BE BLOCKED
    blocked_above, reason_above = om._check_dynamic_sr_boundary(ACTION_BUY, 4142.10, st)
    assert blocked_above is True
    assert "Blocked BUY probing above resistance ceiling" in reason_above

    # 3. Confirmed M5 close breakout > 4141.93 + 0.50 (e.g. 4142.50) with base -> ALLOWED
    st.frames["M5"][-3] = {"open": 4139.0, "high": 4140.0, "low": 4137.0, "close": 4137.5}  # red base/pullback bar
    st.frames["M5"][-2] = {"open": 4137.5, "high": 4141.0, "low": 4137.0, "close": 4140.5}
    st.frames["M5"][-1] = {"open": 4140.5, "high": 4143.0, "low": 4140.0, "close": 4142.60}
    blocked_breakout, _ = om._check_dynamic_sr_boundary(ACTION_BUY, 4142.00, st)
    assert blocked_breakout is False

    # 4. Ticket #4908409177 scenario: Entry at 4137.03 (dist=4.90) in DEFENSE mode (buffer expands to $5.08)
    st.frames["M5"][-1]["close"] = 4139.00
    st.daily_pnl_pct = -1.0
    blocked_defense, reason_defense = om._check_dynamic_sr_boundary(ACTION_BUY, 4137.03, st)
    assert blocked_defense is True
    assert "Blocked BUY near resistance ceiling" in reason_defense

    # 5. Ticket #4908580511 scenario: Confirmed M5 breakdown at 4124.19, but entry at 4122.40 (1.79 USD extended) -> TABAYUN BLOCKS!
    st_down = SharedState(
        symbol="XAUUSDm",
        extra={
            "market_regime": "TRENDING_BEAR",
            "sr_resistance": 4135.00,
            "sr_support": 4124.19,
            "struct_event": "LH_LL",
        },
        frames={
            "M5": [
                {"open": 4136.0, "high": 4138.0, "low": 4134.0, "close": 4135.0},
                {"open": 4135.0, "high": 4137.0, "low": 4132.0, "close": 4133.9},
                {"open": 4134.0, "high": 4134.7, "low": 4128.9, "close": 4129.4},
                {"open": 4129.3, "high": 4129.4, "low": 4125.8, "close": 4126.8},
                {"open": 4124.8, "high": 4125.6, "low": 4121.4, "close": 4122.48},  # confirmed close below 4124.19
            ]
        },
    )
    blocked_climax, reason_climax = om._check_dynamic_sr_boundary(ACTION_SELL, 4122.395, st_down)
    assert blocked_climax is True
    assert "Tabayun" in reason_climax


async def test_position_manager_aggressive_scalper_position_awareness() -> None:
    from config.settings import Settings
    client = MockMT5Client()
    s_agg = Settings(
        aggressive_scalper=True,
        hard_loss_clamp_usd=3.50,
        stagnant_min_profit_usd=2.50,
        stagnant_harvest_seconds=120,
    )
    pm = PositionManager(client=client, settings=s_agg)
    pos = await _open_position(client, sl=2335.0, volume=0.05)
    pm.track(pos)

    # 1. Intra-candle noise at 20s (held < 60s) with 12 pips loss (-$6.00) on 0.05 lot:
    # Must NOT trigger catastrophic gap cut!
    now = utcnow()
    pm._states[pos.ticket].opened_at = now - timedelta(seconds=20)
    pos.profit = -6.00
    actions_noise = await pm.manage(pos, price=2349.0, now=now)
    assert "juggler_catastrophic_gap_cut" not in actions_noise
    assert len(await client.positions("XAUUSD")) == 1

    # 2. Genuine flash gap spike (-$15.00 = 30 pips): triggers catastrophic gap cut!
    pos.profit = -15.00
    actions_gap = await pm.manage(pos, price=2348.0, now=now)
    assert "juggler_catastrophic_gap_cut" in actions_gap
    assert await client.positions("XAUUSD") == []


async def test_anti_rescue_piramida_blocks_averaging() -> None:
    """Verify that if existing positions originated from PYRAMID scaling, averaging rescue layers are blocked."""
    client = MockMT5Client()
    om = OrderManager(client=client, settings=settings)

    # An existing pyramid position is open
    pyr_pos = Position(
        ticket=7001,
        symbol=settings.mt5_symbol,
        side=SIDE_SELL,
        volume=0.03,
        price_open=4061.50,
        price_current=4063.50,
        profit=-6.0,
    )
    pyr_pos.comment = "PYRAMID L2 SELL"
    client._positions[7001] = pyr_pos

    dec = _decision(action=ACTION_SELL, score=-1.5, confidence=0.75, size=0.03, entry=4063.50)
    res = await om.execute(dec)
    assert res is not None
    assert res.ok is False
    assert "pyramid positions cannot be rescued with averaging" in (res.reason or "")


async def test_pyramid_transition_promotes_bep_or_harvests() -> None:
    """Verify that when anchor trade is harvested, pyramid position is checked by agent pattern."""
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)

    # Anchor trade and pyramid trade
    anchor = Position(ticket=8001, symbol="XAUUSD", side=SIDE_SELL, volume=0.03, price_open=4065.0, price_current=4057.0, profit=8.0)
    pyramid = Position(ticket=8002, symbol="XAUUSD", side=SIDE_SELL, volume=0.03, price_open=4062.0, price_current=4057.0, profit=5.0)
    pyramid.comment = "PYRAMID L2 SELL"
    client._positions[8001] = anchor
    client._positions[8002] = pyramid
    pm.track(anchor)
    pm.track(pyramid)

    # Context with confirming continuation decision
    dec_cont = _decision(action=ACTION_SELL, score=-1.8, confidence=0.75)
    ctx_cont = {"decision": dec_cont, "live_avg_win": 2.50}

    # Harvest anchor trade -> pyramid should be promoted with BEP locked!
    actions = await pm.manage(anchor, price=4057.0, context=ctx_cont)
    assert "juggler_runner_harvest" in actions
    assert "pyramid_promoted_bep" in actions
    # Pyramid position still alive, SL secured at entry - 0.10 (for SELL)
    assert len(await client.positions("XAUUSD")) == 1
    refreshed_pyr = (await client.positions("XAUUSD"))[0]
    assert refreshed_pyr.sl == round(4062.0 - 0.10, 2)

    # Next scenario: if pattern is weakened/opposing, pyramid is harvested with anchor
    client._positions.clear()
    anchor2 = Position(ticket=8003, symbol="XAUUSD", side=SIDE_SELL, volume=0.03, price_open=4065.0, price_current=4057.0, profit=8.0)
    pyramid2 = Position(ticket=8004, symbol="XAUUSD", side=SIDE_SELL, volume=0.03, price_open=4062.0, price_current=4057.0, profit=-2.0)
    pyramid2.comment = "PYRAMID L2 SELL"
    client._positions[8003] = anchor2
    client._positions[8004] = pyramid2
    pm.track(anchor2)
    pm.track(pyramid2)

    dec_weak = _decision(action="HOLD", score=0.0, confidence=0.40)
    ctx_weak = {"decision": dec_weak, "live_avg_win": 2.50}

    actions2 = await pm.manage(anchor2, price=4057.0, context=ctx_weak)
    assert "juggler_runner_harvest" in actions2
    assert "pyramid_harvested_with_anchor" in actions2
    assert await client.positions("XAUUSD") == []


async def test_dynamic_basket_catastrophic_cut_anchored_to_juggler() -> None:
    """Verify that basket cutloss clamp dynamically scales with DEFENSE vs BALANCED modes instead of static -$38."""
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)

    # 2 positions in a rescue basket (total vol = 0.06)
    pos1 = Position(ticket=9001, symbol="XAUUSD", side=SIDE_SELL, volume=0.03, price_open=4061.5, price_current=4065.0, profit=-10.5)
    pos2 = Position(ticket=9002, symbol="XAUUSD", side=SIDE_SELL, volume=0.03, price_open=4063.5, price_current=4065.0, profit=-4.5)
    pos2.comment = "RESCUE L2 SELL"
    positions = [pos1, pos2]

    # In DEFENSE mode (pnl < 0), clamp is tight (~$9 - $10). Loss of -$15.00 MUST TRIGGER CATASTROPHIC CUT!
    ctx_def = {"daily_pnl_pct": -1.0, "live_avg_win": 2.50}
    actions_def = await pm.manage_basket(positions, current_bid=4065.0, current_ask=4065.2, context=ctx_def)
    assert "basket_cut_closed" in actions_def




