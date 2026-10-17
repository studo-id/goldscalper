"""Backtest engine: replay historical candles through the live decision brain.

The engine reuses the *real* :class:`~agents.orchestrator.Orchestrator`,
:class:`~execution.order_manager.OrderManager`,
:class:`~execution.position_manager.PositionManager` and the pre-trade
:func:`~execution.risk_gate.apply` gate, swapping only the MT5 client for a
:class:`~backtest.sim_broker.SimBroker`. Signals are computed from bars strictly
older than the current bar (no look-ahead); entries fill at the bar open and
exits are evaluated against the bar's high/low range.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agents.divisions import build_all_agents
from agents.learning import BanditOptimizer, PatternLibrary
from agents.message_bus import MemoryBus
from agents.orchestrator import Orchestrator
from agents.registry import AgentRegistry
from agents.state import SharedState
from backtest.metrics import compute_stats
from backtest.sim_broker import SimBroker
from config.logging import get_logger
from config.settings import Settings
from config.settings import settings as default_settings
from core.indicators import atr
from core.market_data import TIMEFRAMES, Bars, Candle
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from execution.risk_gate import apply as risk_gate_apply
from spk.decision import ACTION_HOLD

log = get_logger("backtest.engine")

_FRAME_DEPTH = 300


@dataclass
class BacktestResult:
    bars: int
    initial_balance: float
    final_equity: float
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "bars": self.bars,
            "initial_balance": self.initial_balance,
            "final_equity": round(self.final_equity, 2),
            **self.stats,
        }


class BacktestEngine:
    """Replay historical OHLCV through the full agent stack."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        registry: AgentRegistry | None = None,
        broker: SimBroker | None = None,
        initial_balance: float = 10_000.0,
        base_timeframe: str = "M1",
        learn: bool = True,
    ) -> None:
        self.settings = settings or default_settings
        self.initial_balance = initial_balance
        self.base_timeframe = base_timeframe
        self.learn = learn

        self.registry = registry or self._build_registry()
        self.broker = broker or SimBroker(
            self.settings.mt5_symbol,
            contract_size=self.settings.contract_size,
            spread=0.30,
            magic=self.settings.mt5_magic,
        )
        self.order_manager = OrderManager(self.broker, self.settings)
        self.position_manager = PositionManager(self.broker, self.settings)
        self.bandit = BanditOptimizer()
        self.patterns = PatternLibrary()

        self._frames: dict[str, list[Candle]] = {}
        self._all: dict[str, list[Candle]] = {}
        self._index: dict[str, list[datetime]] = {}
        self.orchestrator = Orchestrator(
            self.registry,
            settings=self.settings,
            bus=MemoryBus(),
            state_builder=self._build_state,
            risk_gate=risk_gate_apply,
            broadcast=False,
            bandit=self.bandit,
            pattern_library=self.patterns,
        )

    def _build_registry(self) -> AgentRegistry:
        registry = AgentRegistry()
        registry.register_all(build_all_agents())
        return registry

    # --- state -----------------------------------------------------------------
    def _build_state(self) -> SharedState:
        price = self.broker.price
        half = self.broker.spread / 2.0
        return SharedState(
            symbol=self.settings.mt5_symbol,
            frames=self._frames,
            bid=price - half,
            ask=price + half,
            spread_points=(self.broker.spread * 10.0),
            equity=self._equity(),
            balance=self.initial_balance + self._realized_pnl(),
        )

    def _realized_pnl(self) -> float:
        return sum(float(t["pnl"]) for t in self.broker.realized)

    def _unrealized(self) -> float:
        return sum(p.profit for p in self.broker._positions.values())

    def _equity(self) -> float:
        return self.initial_balance + self._realized_pnl() + self._unrealized()

    def _slice_frames(self, t: datetime) -> None:
        frames: dict[str, list[Candle]] = {}
        for tf in TIMEFRAMES:
            times = self._index.get(tf)
            rows = self._all.get(tf) or []
            if not times or not rows:
                continue
            idx = bisect_left(times, t)  # bars strictly before t
            if idx <= 0:
                continue
            lo = max(0, idx - _FRAME_DEPTH)
            frames[tf] = rows[lo:idx]
        self._frames = frames

    def _atr(self) -> float | None:
        bars = Bars.from_rows(self._frames.get("M15") or [])
        if bars.n < 15:
            return None
        return atr(bars.highs, bars.lows, bars.closes, 14)

    # --- exits within a bar ----------------------------------------------------
    async def _check_exits(self, bar: Candle) -> None:
        atr_val = self._atr()
        for pos in list(self.broker.open_positions()):
            if pos.is_long:
                if pos.sl is not None and bar.low <= pos.sl:
                    await self.broker.close_position(pos.ticket, price=pos.sl)
                    self.position_manager.untrack(pos.ticket)
                    await self._on_close(pos.ticket)
                    continue
                if pos.tp is not None and bar.high >= pos.tp:
                    await self.broker.close_position(pos.ticket, price=pos.tp)
                    self.position_manager.untrack(pos.ticket)
                    await self._on_close(pos.ticket)
                    continue
            else:
                if pos.sl is not None and bar.high >= pos.sl:
                    await self.broker.close_position(pos.ticket, price=pos.sl)
                    self.position_manager.untrack(pos.ticket)
                    await self._on_close(pos.ticket)
                    continue
                if pos.tp is not None and bar.low <= pos.tp:
                    await self.broker.close_position(pos.ticket, price=pos.tp)
                    self.position_manager.untrack(pos.ticket)
                    await self._on_close(pos.ticket)
                    continue

            try:
                before = len(self.broker.realized)
                await self.position_manager.manage(pos, bar.close, atr=atr_val)
                if len(self.broker.realized) > before:
                    await self._on_close(pos.ticket)
            except Exception as exc:  # noqa: BLE001
                log.debug("manage failed ticket=%s: %s", pos.ticket, exc)

    async def _on_close(self, ticket: int) -> None:
        if not self.learn:
            return
        fill = next((t for t in reversed(self.broker.realized) if t["ticket"] == ticket), None)
        if fill is None:
            return
        try:
            await self.orchestrator.on_trade_closed(
                {
                    "id": f"bt-{ticket}",
                    "pnl": fill["pnl"],
                    "pips": fill["pips"],
                    "duration_s": 0,
                    "direction": fill["side"],
                    "symbol": self.settings.mt5_symbol,
                },
                {},
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("learning on close failed: %s", exc)

    # --- run -------------------------------------------------------------------
    async def run(self, history: dict[str, list[Candle]]) -> BacktestResult:
        base = sorted(history.get(self.base_timeframe, []), key=lambda c: c.time)
        if not base:
            raise ValueError(f"no {self.base_timeframe} candles in history")

        self._frames = {
            tf: sorted(rows, key=lambda c: c.time)
            for tf, rows in history.items()
            if rows
        }
        self._all = self._frames
        self._index = {tf: [c.time for c in rows] for tf, rows in self._all.items()}

        await self.broker.connect()
        equity_curve: list[float] = []

        for bar in base:
            self._slice_frames(bar.time)
            self.broker.set_market(bar.open, bar.time)

            decision = await self.orchestrator.run_cycle()
            if decision.action != ACTION_HOLD and not decision.hard_veto and decision.size:
                state = self.orchestrator.last_state
                await self.order_manager.execute(decision, state)

            self.broker.set_market(bar.close, bar.time)
            await self._check_exits(bar)
            self.broker.set_market(bar.close, bar.time)
            equity_curve.append(self._equity())

        # flatten at the end
        for pos in list(self.broker.open_positions()):
            await self.broker.close_position(pos.ticket, price=self.broker.price)
            await self._on_close(pos.ticket)
        await self.broker.disconnect()

        stats = compute_stats(self.broker.realized, equity_curve, self.initial_balance)
        result = BacktestResult(
            bars=len(base),
            initial_balance=self.initial_balance,
            final_equity=self._equity(),
            trades=list(self.broker.realized),
            equity_curve=equity_curve,
            stats=stats,
        )
        log.info("backtest done: %s", result.summary())
        return result


async def load_history_from_repo(
    repo: Any,
    symbol: str,
    timeframes: list[str] | None = None,
    limit: int = 5000,
) -> dict[str, list[Candle]]:
    """Load ascending OHLCV per timeframe from a MarketDataRepository."""
    tfs = timeframes or TIMEFRAMES
    history: dict[str, list[Candle]] = {}
    for tf in tfs:
        rows = await repo.fetch_candles(symbol, tf, limit=limit)
        candles = [
            Candle(
                symbol=r["symbol"],
                timeframe=r["timeframe"],
                time=r["time"],
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r.get("volume") or 0.0),
                spread_avg=float(r.get("spread_avg") or 0.0),
            )
            for r in rows
        ]
        if candles:
            candles.sort(key=lambda c: c.time)
            history[tf] = candles
    return history


__all__ = ["BacktestEngine", "BacktestResult", "load_history_from_repo"]
