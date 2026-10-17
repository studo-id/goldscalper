"""Simulated broker for backtesting.

Implements the same async trading surface as the live MT5 clients
(``order_send`` / ``positions`` / ``close_position`` / ``modify_position``) but
fills against a price the replay engine sets per bar. This lets the exact same
:class:`~execution.order_manager.OrderManager` and
:class:`~execution.position_manager.PositionManager` drive the backtest as the
live bot — no divergent logic.
"""

from __future__ import annotations

from datetime import datetime

from core.mt5_connector import (
    SIDE_BUY,
    OrderRequest,
    OrderResult,
    Position,
    Quote,
)


class SimBroker:
    """In-memory broker with spread-aware market fills and realized PnL."""

    def __init__(
        self,
        symbol: str = "XAUUSD",
        *,
        contract_size: float = 100.0,
        spread: float = 0.30,
        magic: int = 990001,
    ) -> None:
        self.symbol = symbol
        self.contract_size = contract_size
        self.spread = spread
        self.magic = magic
        self._positions: dict[int, Position] = {}
        self._next_ticket = 1
        self._price = 0.0
        self._time: datetime | None = None
        self._connected = False
        self.realized: list[dict] = []

    # --- connection ------------------------------------------------------------
    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    # --- market ----------------------------------------------------------------
    def set_market(self, price: float, time: datetime | None = None) -> None:
        """Advance the simulated price and mark open positions to market."""
        self._price = float(price)
        if time is not None:
            self._time = time
        for pos in self._positions.values():
            pos.price_current = self._price
            pos.profit = self._profit(pos, self._price, pos.volume)

    @property
    def price(self) -> float:
        return self._price

    async def symbol_tick(self, symbol: str) -> Quote | None:
        half = self.spread / 2.0
        return Quote(
            symbol=symbol,
            time=self._time or datetime.min,
            bid=self._price - half,
            ask=self._price + half,
        )

    async def copy_rates(self, symbol: str, timeframe: str, start, end) -> list:
        return []

    # --- trading ---------------------------------------------------------------
    def _profit(self, pos: Position, price: float, volume: float) -> float:
        direction = 1.0 if pos.is_long else -1.0
        return (price - pos.price_open) * volume * self.contract_size * direction

    async def order_send(self, request: OrderRequest) -> OrderResult:
        if not self._connected or self._price <= 0:
            return OrderResult(ok=False, comment="sim broker not ready")
        half = self.spread / 2.0
        if request.side == SIDE_BUY:
            fill = (request.price + half) if request.price else self._price + half
        else:
            fill = (request.price - half) if request.price else self._price - half
        ticket = self._next_ticket
        self._next_ticket += 1
        pos = Position(
            ticket=ticket,
            symbol=request.symbol or self.symbol,
            side=request.side,
            volume=request.volume,
            price_open=fill,
            sl=request.sl,
            tp=request.tp,
            price_current=fill,
            profit=0.0,
            magic=request.magic or self.magic,
            time=self._time,
        )
        self._positions[ticket] = pos
        return OrderResult(
            ok=True, ticket=ticket, price=fill, volume=request.volume, retcode=0
        )

    async def positions(self, symbol: str | None = None) -> list[Position]:
        if symbol is None:
            return list(self._positions.values())
        return [p for p in self._positions.values() if p.symbol == symbol]

    def open_positions(self) -> list[Position]:
        """Synchronous snapshot of open positions (backtest convenience)."""
        return list(self._positions.values())

    async def close_position(
        self, ticket: int, price: float | None = None, volume: float | None = None
    ) -> OrderResult:
        pos = self._positions.get(ticket)
        if pos is None:
            return OrderResult(ok=False, comment="no such position")
        exit_price = price if price is not None else (pos.price_current or self._price)
        close_volume = pos.volume if volume is None else min(volume, pos.volume)
        if close_volume <= 0:
            return OrderResult(ok=False, comment="zero volume")

        pnl = self._profit(pos, exit_price, close_volume)
        direction = 1.0 if pos.is_long else -1.0
        pips = (exit_price - pos.price_open) * 10.0 * direction
        self.realized.append(
            {
                "ticket": ticket,
                "side": pos.side,
                "entry": pos.price_open,
                "exit": exit_price,
                "volume": close_volume,
                "pnl": pnl,
                "pips": pips,
                "time": self._time,
            }
        )
        if close_volume >= pos.volume:
            self._positions.pop(ticket, None)
        else:
            pos.volume = round(pos.volume - close_volume, 4)
        return OrderResult(ok=True, ticket=ticket, price=exit_price, volume=close_volume)

    async def modify_position(
        self, ticket: int, sl: float | None, tp: float | None
    ) -> OrderResult:
        pos = self._positions.get(ticket)
        if pos is None:
            return OrderResult(ok=False, comment="no such position")
        if sl is not None:
            pos.sl = sl
        if tp is not None:
            pos.tp = tp
        return OrderResult(ok=True, ticket=ticket)


__all__ = ["SimBroker"]
