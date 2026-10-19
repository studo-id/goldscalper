"""Tests for the execution layer (mock MT5)."""

from __future__ import annotations

from datetime import datetime, timedelta

from agents.state import UTC, utcnow
from config.settings import settings
from core.mt5_connector import SIDE_BUY, MockMT5Client, OrderRequest, Position
from core.notifier import Notifier
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from spk.decision import ACTION_BUY, STRENGTH_STRONG, SPKDecision


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

    # 2. When M1 and M5 both oppose our position -> Early Invalidation Cut!
    adverse_signals = [
        AgentSignal(agent_id="TF-M1-Sniper", division="timeframe", vote=-1, confidence=0.8),
        AgentSignal(agent_id="TF-M5-Inspector", division="timeframe", vote=-1, confidence=0.7),
    ]
    dec_adv = SPKDecision(action=ACTION_BUY, score=-3.0, confidence=0.8, votes=adverse_signals)
    pm._states[pos.ticket].opened_at = now - timedelta(seconds=60)  # Held 60s
    pos.profit = -7.00  # floating loss exceeding early threshold ($7.00 >= $6.40)
    actions_cut = await pm.manage(pos, price=2349.5, now=now, context={"decision": dec_adv})
    assert "watchdog_early_invalidation_cut" in actions_cut
    assert await client.positions("XAUUSD") == []


async def test_fast_breakeven_lock() -> None:
    client = MockMT5Client()
    pm = PositionManager(client=client, settings=settings)
    now = utcnow()
    pos = await _open_position(client, sl=2340.0, volume=0.10)
    pos.profit = 2.50  # +25 pips on 0.10 lot = $2.50 >= be_trigger_usd $1.80

    actions = await pm.manage(pos, price=2350.25, now=now)
    assert "breakeven_locked" in actions
    refreshed = (await client.positions("XAUUSD"))[0]
    assert refreshed.sl == round(pos.price_open + 0.10, 2)  # Locked into entry + 0.10


