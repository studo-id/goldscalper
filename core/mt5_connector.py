"""MT5 connectivity: quotes, history, and a live tick streamer.

Three interchangeable clients behind one interface (:class:`MT5Client`):

* :class:`MockMT5Client`   — synthetic data, runs anywhere (dev/tests/Linux).
* :class:`NativeMT5Client` — the real ``MetaTrader5`` package (Windows only).
* :class:`BridgeMT5Client` — HTTP bridge to a Windows MT5 host (httpx).

:func:`create_client` picks the right one from settings. The container runs
Linux, so native MT5 is only used when the bot runs on the Windows host itself.
"""

from __future__ import annotations

import asyncio
import random
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc
from typing import Any, Protocol

from config.logging import get_logger
from config.settings import Settings
from config.settings import settings as default_settings
from core.market_data import (
    TIMEFRAMES,
    Candle,
    MarketDataCache,
    Tick,
    TimeframeAggregator,
    tf_seconds,
)

log = get_logger("core.mt5")


class MT5Error(RuntimeError):
    """Raised for MT5 connection/operation failures."""


@dataclass(slots=True)
class Quote:
    symbol: str
    time: datetime
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return max(0.0, self.ask - self.bid)

    def as_tick(self, volume: float = 0.0) -> Tick:
        return Tick(symbol=self.symbol, time=self.time, bid=self.bid, ask=self.ask, volume=volume)


SIDE_BUY = "BUY"
SIDE_SELL = "SELL"


@dataclass(slots=True)
class OrderRequest:
    """A market or limit order to submit to MT5."""

    symbol: str
    side: str  # SIDE_BUY / SIDE_SELL
    volume: float
    price: float | None = None  # None => market order
    sl: float | None = None
    tp: float | None = None
    magic: int = 0
    deviation: int = 20
    comment: str = ""
    order_type: str = "market"  # "market" | "limit"

    @property
    def is_market(self) -> bool:
        return self.order_type == "market" or self.price is None


@dataclass(slots=True)
class OrderResult:
    ok: bool
    ticket: int | None = None
    price: float | None = None
    volume: float = 0.0
    retcode: int = 0
    comment: str = ""


@dataclass(slots=True)
class Position:
    ticket: int
    symbol: str
    side: str
    volume: float
    price_open: float
    sl: float | None = None
    tp: float | None = None
    price_current: float = 0.0
    profit: float = 0.0
    magic: int = 0
    time: datetime | None = None

    @property
    def is_long(self) -> bool:
        return self.side == SIDE_BUY


class MT5Client(Protocol):
    """Interface every MT5 client implementation satisfies."""

    async def connect(self) -> bool: ...
    async def disconnect(self) -> None: ...
    @property
    def connected(self) -> bool: ...
    async def symbol_tick(self, symbol: str) -> Quote | None: ...
    async def copy_rates(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Candle]: ...
    async def order_send(self, request: OrderRequest) -> OrderResult: ...
    async def positions(self, symbol: str | None = None) -> list[Position]: ...
    async def close_position(
        self, ticket: int, price: float | None = None, volume: float | None = None
    ) -> OrderResult: ...
    async def modify_position(
        self, ticket: int, sl: float | None, tp: float | None
    ) -> OrderResult: ...
    async def account_info(self) -> dict[str, Any]: ...
    @property
    def trade_allowed(self) -> bool: ...


# --------------------------------------------------------------------------- #
# Mock client
# --------------------------------------------------------------------------- #
class MockMT5Client:
    """Deterministic synthetic market (random walk) for development/tests."""

    def __init__(
        self,
        start_price: float = 2350.0,
        spread: float = 0.20,
        volatility: float = 0.05,
        seed: int = 42,
        time_provider: Any | None = None,
    ) -> None:
        self.start_price = start_price
        self.spread = spread
        self.volatility = volatility
        self._rng = random.Random(seed)  # noqa: S311 - synthetic mock data, not crypto
        self._price = start_price
        self._connected = False
        self._time_provider = time_provider or (lambda: datetime.now(UTC))
        self._positions: dict[int, Position] = {}
        self._next_ticket = 100000

    @property
    def trade_allowed(self) -> bool:
        return True

    async def connect(self) -> bool:
        self._connected = True
        log.info("mock MT5 connected (price=%.2f)", self._price)
        return True

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def account_info(self) -> dict[str, Any]:
        unrealized = sum(p.profit for p in self._positions.values())
        return {
            "login": 434366152,
            "balance": 10000.0,
            "equity": round(10000.0 + unrealized, 2),
            "profit": round(unrealized, 2),
            "margin_free": round(10000.0 + unrealized, 2),
            "server": "Exness-MT5Trial7",
        }

    def _step(self) -> float:
        self._price += self._rng.gauss(0.0, self.volatility)
        return self._price

    async def symbol_tick(self, symbol: str) -> Quote | None:
        price = self._step()
        half = self.spread / 2.0
        return Quote(symbol=symbol, time=self._time_provider(), bid=price - half, ask=price + half)

    async def copy_rates(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Candle]:
        """Generate synthetic candles across [start, end) for the timeframe."""
        secs = tf_seconds(timeframe)
        out: list[Candle] = []
        price = self.start_price
        cur = int(start.timestamp()) - (int(start.timestamp()) % secs)
        end_epoch = int(end.timestamp())
        # stable per-range seed (crc32) so re-runs reproduce the same candles
        seed = zlib.crc32(f"{symbol}|{timeframe}|{cur}|{end_epoch}".encode())
        rng = random.Random(seed)  # noqa: S311 - synthetic mock data, not crypto
        while cur < end_epoch:
            o = price
            moves = [rng.gauss(0.0, self.volatility * (secs / 60) ** 0.5) for _ in range(4)]
            h = max(o, o + max(moves))
            low = min(o, o + min(moves))
            c = o + sum(moves) / len(moves)
            volume = abs(rng.gauss(100.0, 25.0))
            out.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    time=datetime.fromtimestamp(cur, tz=UTC),
                    open=round(o, 2),
                    high=round(h, 2),
                    low=round(low, 2),
                    close=round(c, 2),
                    volume=round(volume, 2),
                    spread_avg=self.spread,
                )
            )
            price = c
            cur += secs
        return out

    # --- trading (simulated fills) --------------------------------------------
    async def order_send(self, request: OrderRequest) -> OrderResult:
        tick = await self.symbol_tick(request.symbol)
        assert tick is not None
        price = request.price if not request.is_market else (
            tick.ask if request.side == SIDE_BUY else tick.bid
        )
        assert price is not None
        self._next_ticket += 1
        ticket = self._next_ticket
        self._positions[ticket] = Position(
            ticket=ticket,
            symbol=request.symbol,
            side=request.side,
            volume=request.volume,
            price_open=price,
            sl=request.sl,
            tp=request.tp,
            price_current=price,
            profit=0.0,
            magic=request.magic,
            time=self._time_provider(),
        )
        log.info("mock order filled: %s %.2f %s @ %.2f", request.side, request.volume,
                 request.symbol, price)
        return OrderResult(
            ok=True, ticket=ticket, price=price, volume=request.volume, retcode=0,
            comment="mock fill",
        )

    async def positions(self, symbol: str | None = None) -> list[Position]:
        tick_price = self._price
        out: list[Position] = []
        for pos in self._positions.values():
            if symbol is not None and pos.symbol != symbol:
                continue
            pos.price_current = tick_price
            direction = 1.0 if pos.is_long else -1.0
            pos.profit = round((tick_price - pos.price_open) * direction * pos.volume, 2)
            out.append(pos)
        return out

    async def close_position(
        self, ticket: int, price: float | None = None, volume: float | None = None
    ) -> OrderResult:
        pos = self._positions.get(ticket)
        if pos is None:
            return OrderResult(ok=False, retcode=1, comment="position not found")
        exit_price = price if price is not None else self._price
        close_volume = min(volume or pos.volume, pos.volume)
        if close_volume >= pos.volume:
            self._positions.pop(ticket, None)
        else:
            pos.volume = round(pos.volume - close_volume, 4)
        return OrderResult(
            ok=True, ticket=ticket, price=exit_price, volume=close_volume, retcode=0,
            comment="mock close",
        )

    async def modify_position(
        self, ticket: int, sl: float | None, tp: float | None
    ) -> OrderResult:
        pos = self._positions.get(ticket)
        if pos is None:
            return OrderResult(ok=False, retcode=1, comment="position not found")
        if sl is not None:
            pos.sl = sl
        if tp is not None:
            pos.tp = tp
        return OrderResult(ok=True, ticket=ticket, retcode=0, comment="mock modify")


# --------------------------------------------------------------------------- #
# Native client (Windows only)
# --------------------------------------------------------------------------- #
class NativeMT5Client:
    """Wraps the official ``MetaTrader5`` package (Windows only)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or default_settings
        self._mt5: Any | None = None
        self._connected = False

    def _load(self) -> Any:
        if self._mt5 is None:
            try:
                import MetaTrader5 as mt5  # type: ignore  # noqa: N813
            except Exception:
                try:
                    from mt5linux import MetaTrader5  # type: ignore

                    rpyc_host = getattr(self.s, "mt5_rpyc_host", "mt5")
                    rpyc_port = getattr(self.s, "mt5_rpyc_port", 8001)
                    mt5 = MetaTrader5(host=rpyc_host, port=rpyc_port)
                except Exception as exc:
                    raise MT5Error(
                        "Neither MetaTrader5 nor mt5linux package is available; use mock"
                    ) from exc
            self._mt5 = mt5
        return self._mt5

    async def connect(self) -> bool:
        mt5 = self._load()
        kwargs: dict[str, Any] = {
            "login": self.s.mt5_login,
            "password": self.s.mt5_password,
            "server": self.s.mt5_server,
        }
        if self.s.mt5_path:
            kwargs["path"] = self.s.mt5_path
        ok = await asyncio.to_thread(mt5.initialize, **kwargs)
        if not ok:
            raise MT5Error(f"MT5 initialize failed: {mt5.last_error()}")
        self._connected = True
        log.info("MT5 connected to %s", self.s.mt5_server)
        return True

    async def disconnect(self) -> None:
        if self._mt5 is not None:
            await asyncio.to_thread(self._mt5.shutdown)
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def trade_allowed(self) -> bool:
        if not self._connected or self._mt5 is None:
            return False
        try:
            info = self._mt5.terminal_info()
            return bool(getattr(info, "trade_allowed", True))
        except Exception:
            return True

    def _tf_const(self, timeframe: str) -> Any:
        mt5 = self._load()
        mapping = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
        }
        return mapping[timeframe.upper()]

    async def symbol_tick(self, symbol: str) -> Quote | None:
        mt5 = self._load()
        tick = await asyncio.to_thread(mt5.symbol_info_tick, symbol)
        if tick is None:
            return None
        return Quote(
            symbol=symbol,
            time=datetime.fromtimestamp(tick.time, tz=UTC),
            bid=float(tick.bid),
            ask=float(tick.ask),
        )

    async def copy_rates(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Candle]:
        mt5 = self._load()
        rates = await asyncio.to_thread(
            mt5.copy_rates_range, symbol, self._tf_const(timeframe), start, end
        )
        if rates is None:
            raise MT5Error(f"copy_rates_range failed: {mt5.last_error()}")
        out: list[Candle] = []
        for r in rates:
            out.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    time=datetime.fromtimestamp(int(r["time"]), tz=UTC),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r["tick_volume"]),
                    spread_avg=float(r["spread"]),
                )
            )
        return out

    # --- trading --------------------------------------------------------------
    async def order_send(self, request: OrderRequest) -> OrderResult:
        mt5 = self._load()
        is_buy = request.side == SIDE_BUY
        if request.is_market:
            tick = await self.symbol_tick(request.symbol)
            if tick is None:
                return OrderResult(ok=False, retcode=-1, comment="no tick")
            price = tick.ask if is_buy else tick.bid
            action = mt5.TRADE_ACTION_DEAL
            order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        else:
            price = request.price
            action = mt5.TRADE_ACTION_PENDING
            order_type = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT

        if price is None:
            return OrderResult(ok=False, retcode=-1, comment="no price")

        payload = {
            "action": action,
            "symbol": request.symbol,
            "volume": float(request.volume),
            "type": order_type,
            "price": float(price),
            "deviation": request.deviation,
            "magic": request.magic,
            "comment": request.comment,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if request.sl is not None:
            payload["sl"] = float(request.sl)
        if request.tp is not None:
            payload["tp"] = float(request.tp)
        if not request.is_market:
            payload["type_time"] = mt5.ORDER_TIME_GTC
        result = await asyncio.to_thread(mt5.order_send, payload)
        if result is None:
            return OrderResult(ok=False, retcode=-1, comment=str(mt5.last_error()))
        raw_price = getattr(result, "price", price) or price
        final_price = float(raw_price) if raw_price is not None else 0.0
        return OrderResult(
            ok=result.retcode == mt5.TRADE_RETCODE_DONE,
            ticket=int(getattr(result, "order", 0)) or None,
            price=final_price,
            volume=float(getattr(result, "volume", request.volume)),
            retcode=int(result.retcode),
            comment=str(getattr(result, "comment", "")),
        )

    async def positions(self, symbol: str | None = None) -> list[Position]:
        mt5 = self._load()
        if symbol:
            raw = await asyncio.to_thread(mt5.positions_get, symbol=symbol)
        else:
            raw = await asyncio.to_thread(mt5.positions_get)
        out: list[Position] = []
        for p in raw or []:
            out.append(
                Position(
                    ticket=int(p.ticket),
                    symbol=p.symbol,
                    side=SIDE_BUY if p.type == mt5.POSITION_TYPE_BUY else SIDE_SELL,
                    volume=float(p.volume),
                    price_open=float(p.price_open),
                    sl=float(p.sl) or None,
                    tp=float(p.tp) or None,
                    price_current=float(p.price_current),
                    profit=float(p.profit),
                    magic=int(p.magic),
                    time=datetime.fromtimestamp(p.time, tz=UTC),
                )
            )
        return out

    async def close_position(
        self, ticket: int, price: float | None = None, volume: float | None = None
    ) -> OrderResult:
        mt5 = self._load()
        current = [p for p in await self.positions() if p.ticket == ticket]
        if not current:
            return OrderResult(ok=False, retcode=-1, comment="position not found")
        pos = current[0]
        tick = await self.symbol_tick(pos.symbol)
        if tick is None:
            return OrderResult(ok=False, retcode=-1, comment="no tick")
        is_long = pos.is_long
        payload = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": pos.symbol,
            "volume": float(volume or pos.volume),
            "type": mt5.ORDER_TYPE_SELL if is_long else mt5.ORDER_TYPE_BUY,
            "price": float(tick.bid if is_long else tick.ask),
            "deviation": self.s.mt5_deviation,
            "magic": pos.magic,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "comment": "close",
        }
        result = await asyncio.to_thread(mt5.order_send, payload)
        if result is None:
            return OrderResult(ok=False, retcode=-1, comment=str(mt5.last_error()))
        return OrderResult(
            ok=result.retcode == mt5.TRADE_RETCODE_DONE,
            ticket=ticket,
            price=float(getattr(result, "price", 0.0) or 0.0),
            retcode=int(result.retcode),
            comment=str(getattr(result, "comment", "")),
        )

    async def modify_position(
        self, ticket: int, sl: float | None, tp: float | None
    ) -> OrderResult:
        mt5 = self._load()
        payload = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl": float(sl) if sl is not None else 0.0,
            "tp": float(tp) if tp is not None else 0.0,
        }
        result = await asyncio.to_thread(mt5.order_send, payload)
        if result is None:
            return OrderResult(ok=False, retcode=-1, comment=str(mt5.last_error()))
        return OrderResult(
            ok=result.retcode == mt5.TRADE_RETCODE_DONE,
            ticket=ticket,
            retcode=int(result.retcode),
            comment=str(getattr(result, "comment", "")),
        )

    async def account_info(self) -> dict[str, Any]:
        mt5 = self._load()
        acc = await asyncio.to_thread(mt5.account_info)
        if acc is None:
            return {}
        return {
            "login": int(getattr(acc, "login", 0)),
            "balance": float(getattr(acc, "balance", 0.0)),
            "equity": float(getattr(acc, "equity", 0.0)),
            "profit": float(getattr(acc, "profit", 0.0)),
            "margin_free": float(getattr(acc, "margin_free", 0.0)),
            "server": str(getattr(acc, "server", "")),
        }


# --------------------------------------------------------------------------- #
# Bridge client (HTTP to Windows host)
# --------------------------------------------------------------------------- #
class BridgeMT5Client:
    """Talks to a thin HTTP bridge running on the Windows MT5 host."""

    def __init__(self, base_url: str, token: str = "", client: Any | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = client
        self._connected = False
        self._trade_allowed = True

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def connect(self) -> bool:
        import httpx

        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=15.0, headers=self._headers()
            )
        resp = await self._client.get("/health")
        resp.raise_for_status()
        self._connected = True
        self._trade_allowed = bool(resp.json().get("trade_allowed", True))
        log.info("MT5 bridge connected: %s (trade_allowed=%s)", self.base_url, self._trade_allowed)
        return True

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def trade_allowed(self) -> bool:
        return self._trade_allowed

    async def symbol_tick(self, symbol: str) -> Quote | None:
        if self._client is None or not self._connected:
            await self.connect()
        try:
            assert self._client is not None
            resp = await self._client.get("/tick", params={"symbol": symbol})
            resp.raise_for_status()
            data = resp.json()
            return Quote(
                symbol=symbol,
                time=datetime.fromisoformat(data["time"]),
                bid=float(data["bid"]),
                ask=float(data["ask"]),
            )
        except Exception:
            self._connected = False
            raise

    async def copy_rates(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Candle]:
        assert self._client is not None
        s_str = start.strftime("%Y-%m-%dT%H:%M:%S")
        e_str = end.strftime("%Y-%m-%dT%H:%M:%S")
        resp = await self._client.get(
            "/rates",
            params={
                "symbol": symbol,
                "timeframe": timeframe,
                "start": s_str,
                "end": e_str,
            },
        )
        resp.raise_for_status()
        candles_data = resp.json().get("candles", [])
        return [
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                time=datetime.fromisoformat(r["time"].replace("Z", "+00:00")),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r.get("volume", 0.0)),
                spread_avg=float(r.get("spread", 0.0)),
            )
            for r in candles_data
        ]

    # --- trading --------------------------------------------------------------
    async def order_send(self, request: OrderRequest) -> OrderResult:
        assert self._client is not None
        resp = await self._client.post("/order", json=asdict(request))
        resp.raise_for_status()
        return self._parse_result(resp.json())

    async def positions(self, symbol: str | None = None) -> list[Position]:
        assert self._client is not None
        params = {"symbol": symbol} if symbol else {}
        resp = await self._client.get("/positions", params=params)
        resp.raise_for_status()
        out: list[Position] = []
        for p in resp.json().get("positions", []):
            out.append(
                Position(
                    ticket=int(p["ticket"]),
                    symbol=p["symbol"],
                    side=p["side"],
                    volume=float(p["volume"]),
                    price_open=float(p["price_open"]),
                    sl=float(p["sl"]) if p.get("sl") else None,
                    tp=float(p["tp"]) if p.get("tp") else None,
                    price_current=float(p.get("price_current", 0.0)),
                    profit=float(p.get("profit", 0.0)),
                    magic=int(p.get("magic", 0)),
                )
            )
        return out

    async def close_position(
        self, ticket: int, price: float | None = None, volume: float | None = None
    ) -> OrderResult:
        assert self._client is not None
        resp = await self._client.post(
            "/close", json={"ticket": ticket, "price": price, "volume": volume}
        )
        resp.raise_for_status()
        return self._parse_result(resp.json())

    async def modify_position(
        self, ticket: int, sl: float | None, tp: float | None
    ) -> OrderResult:
        assert self._client is not None
        resp = await self._client.post(
            "/modify", json={"ticket": ticket, "sl": sl, "tp": tp}
        )
        resp.raise_for_status()
        return self._parse_result(resp.json())

    @staticmethod
    def _parse_result(data: dict[str, Any]) -> OrderResult:
        return OrderResult(
            ok=bool(data.get("ok", False)),
            ticket=int(data["ticket"]) if data.get("ticket") else None,
            price=float(data["price"]) if data.get("price") is not None else None,
            volume=float(data.get("volume", 0.0)),
            retcode=int(data.get("retcode", 0)),
            comment=str(data.get("comment", "")),
        )

    async def account_info(self) -> dict[str, Any]:
        if not self._client:
            return {}
        try:
            resp = await self._client.get("/account")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and ("balance" in data or "equity" in data):
                    self._trade_allowed = bool(data.get("trade_allowed", True))
                    return data
            resp_h = await self._client.get("/health")
            if resp_h.status_code == 200:
                data_h = resp_h.json()
                self._trade_allowed = bool(data_h.get("trade_allowed", True))
                if isinstance(data_h.get("account"), dict):
                    return data_h["account"]
        except Exception:
            pass
        return {}


def create_client(settings: Settings | None = None) -> MT5Client:
    """Select an MT5 client based on settings/platform."""
    s = settings or default_settings
    if s.mt5_bridge_url:
        return BridgeMT5Client(s.mt5_bridge_url, s.mt5_bridge_token)
    if s.mt5_mock:
        return MockMT5Client()
    try:
        return NativeMT5Client(s)
    except Exception:
        log.warning("Native MT5 client unavailable; falling back to MockMT5Client")
        return MockMT5Client()


# --------------------------------------------------------------------------- #
# Tick streamer
# --------------------------------------------------------------------------- #
class TickStreamer:
    """Poll the MT5 client and fan out ticks + closed candles.

    * publishes each tick to a Redis stream (default ``gs:ticks``)
    * aggregates into every timeframe and caches closed candles
    * optionally persists closed candles via a repository
    """

    def __init__(
        self,
        client: MT5Client,
        symbol: str = "XAUUSD",
        bus: Any | None = None,
        cache: MarketDataCache | None = None,
        repo: Any | None = None,
        poll_interval: float = 0.5,
        stream: str = "gs:ticks",
        candle_stream: str = "gs:candles",
    ) -> None:
        self.client = client
        self.symbol = symbol
        self.bus = bus
        self.cache = cache or MarketDataCache()
        self.repo = repo
        self.poll_interval = poll_interval
        self.stream = stream
        self.candle_stream = candle_stream

        self._aggregators = {tf: TimeframeAggregator(symbol, tf) for tf in TIMEFRAMES}
        self._running = False
        self._task: asyncio.Task | None = None
        self.tick_count = 0
        self.candle_count = 0
        self.last_quote: Quote | None = None

    async def _emit_closed(self, candle: Candle) -> None:
        self.candle_count += 1
        self.cache.append(candle)
        if self.bus is not None:
            try:
                payload = candle.as_dict()
                payload["time"] = candle.time.isoformat()
                await self.bus.publish(self.candle_stream, payload)
            except Exception as exc:  # noqa: BLE001
                log.debug("candle publish failed: %s", exc)
        if self.repo is not None:
            try:
                await self.repo.save_candles([candle])
            except Exception as exc:  # noqa: BLE001
                log.warning("candle persist failed: %s", exc)

    async def process_tick(self, quote: Quote) -> None:
        tick = quote.as_tick()
        self.tick_count += 1
        self.last_quote = quote
        if self.bus is not None:
            try:
                await self.bus.publish(
                    self.stream,
                    {
                        "symbol": tick.symbol,
                        "time": tick.time.isoformat(),
                        "bid": tick.bid,
                        "ask": tick.ask,
                        "volume": tick.volume,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("tick publish failed: %s", exc)
        for agg in self._aggregators.values():
            closed = agg.add_tick(tick)
            if closed is not None:
                await self._emit_closed(closed)

    async def run(self) -> None:
        self._running = True
        if not self.client.connected:
            await self.client.connect()
        log.info(
            "tick streamer started (symbol=%s, interval=%.2fs)",
            self.symbol,
            self.poll_interval,
        )
        while self._running:
            try:
                if not self.client.connected:
                    await self.client.connect()
                quote = await self.client.symbol_tick(self.symbol)
                if quote is not None:
                    await self.process_tick(quote)
            except Exception as exc:  # noqa: BLE001 - keep streaming
                log.warning("tick poll error: %s", exc)
            await asyncio.sleep(self.poll_interval)

    def start(self) -> asyncio.Task:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run(), name="mt5-tick-streamer")
        return self._task

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception) as exc:  # noqa: BLE001
                log.debug("tick streamer task ended: %s", exc)
            self._task = None
        await self.client.disconnect()
        log.info(
            "tick streamer stopped (ticks=%d candles=%d)",
            self.tick_count,
            self.candle_count,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "running": self._running,
            "ticks": self.tick_count,
            "candles": self.candle_count,
            "client": type(self.client).__name__,
            "connected": self.client.connected,
            "ts": datetime.now(UTC).isoformat(),
        }


def _now_utc() -> datetime:
    """Small helper for callers/tests."""
    return datetime.now(UTC)


__all__ = [
    "BridgeMT5Client",
    "Candle",
    "MT5Client",
    "MT5Error",
    "MockMT5Client",
    "NativeMT5Client",
    "OrderRequest",
    "OrderResult",
    "Position",
    "Quote",
    "SIDE_BUY",
    "SIDE_SELL",
    "TickStreamer",
    "create_client",
]
