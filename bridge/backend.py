"""MT5 backend: the only place that imports the ``MetaTrader5`` package.

All methods return plain dicts so the FastAPI layer stays a thin serializer and
so tests can inject a fake backend without the MT5 terminal installed.
"""

from __future__ import annotations

try:
    from datetime import UTC, datetime
except ImportError:
    from datetime import datetime, timezone
    UTC = timezone.utc

from typing import Any, Protocol

from bridge.config import BridgeSettings


class BridgeError(RuntimeError):
    """Raised for MT5 initialization or operation failures."""


# Timeframe label -> MetaTrader5 constant attribute name.
_TF_ATTR = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}

_FILLING_ATTR = {
    "IOC": "ORDER_FILLING_IOC",
    "FOK": "ORDER_FILLING_FOK",
    "RETURN": "ORDER_FILLING_RETURN",
}


class BridgeBackend(Protocol):
    """Interface the FastAPI layer depends on."""

    def health(self) -> dict[str, Any]: ...
    def tick(self, symbol: str) -> dict[str, Any]: ...
    def rates(
        self, symbol: str, timeframe: str, start: str, end: str
    ) -> dict[str, Any]: ...
    def order(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def positions(self, symbol: str | None) -> dict[str, Any]: ...
    def close(
        self, ticket: int, price: float | None, volume: float | None
    ) -> dict[str, Any]: ...
    def modify(self, ticket: int, sl: float | None, tp: float | None) -> dict[str, Any]: ...


class MT5Backend:
    """Wraps the official ``MetaTrader5`` package (Windows only, lazy import)."""

    def __init__(self, settings: BridgeSettings) -> None:
        self.s = settings
        self._mt5: Any | None = None
        self._initialized = False

    # --- lifecycle ------------------------------------------------------------
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
                    raise BridgeError(
                        "Neither MetaTrader5 nor mt5linux package is available"
                    ) from exc
            self._mt5 = mt5
        return self._mt5

    def _ensure(self) -> Any:
        mt5 = self._load()
        if not self._initialized:
            kwargs: dict[str, Any] = {}
            if self.s.mt5_path:
                kwargs["path"] = self.s.mt5_path
            if self.s.mt5_login and self.s.mt5_password:
                kwargs["login"] = self.s.mt5_login
                kwargs["password"] = self.s.mt5_password
                if self.s.mt5_server:
                    kwargs["server"] = self.s.mt5_server
            ok = False
            try:
                ok = mt5.initialize(**kwargs)
            except Exception:
                pass
            if not ok:
                ok = mt5.initialize()
            if not ok:
                raise BridgeError(f"MT5 initialize failed: {mt5.last_error()}")
            if self.s.mt5_login and self.s.mt5_password:
                acc = mt5.account_info()
                curr_login = getattr(acc, "login", 0) if acc else 0
                if curr_login != self.s.mt5_login:
                    if not mt5.login(
                        self.s.mt5_login,
                        password=self.s.mt5_password,
                        server=self.s.mt5_server,
                    ):
                        raise BridgeError(f"MT5 login failed: {mt5.last_error()}")
            self._initialized = True
        return mt5

    def shutdown(self) -> None:
        if self._mt5 is not None and self._initialized:
            self._mt5.shutdown()
        self._initialized = False

    # --- helpers --------------------------------------------------------------
    def _select(self, mt5: Any, symbol: str) -> None:
        """Ensure the symbol is present in Market Watch before quoting."""
        info = mt5.symbol_info(symbol)
        if info is None:
            raise BridgeError(f"unknown symbol: {symbol}")
        if not info.visible:
            mt5.symbol_select(symbol, True)

    def _tf(self, mt5: Any, timeframe: str) -> Any:
        attr = _TF_ATTR.get(timeframe.upper())
        if attr is None:
            raise BridgeError(f"unsupported timeframe: {timeframe}")
        return getattr(mt5, attr)

    def _filling(self, mt5: Any) -> Any:
        attr = _FILLING_ATTR.get(self.s.mt5_filling.upper(), "ORDER_FILLING_IOC")
        return getattr(mt5, attr)

    @staticmethod
    def _result(mt5: Any, raw: Any, *, ticket: int | None = None,
                price: float | None = None, volume: float = 0.0) -> dict[str, Any]:
        if raw is None:
            return {
                "ok": False,
                "ticket": ticket,
                "price": price,
                "volume": volume,
                "retcode": -1,
                "comment": str(mt5.last_error()),
            }
        retcode = int(raw.retcode)
        return {
            "ok": retcode == mt5.TRADE_RETCODE_DONE,
            "ticket": ticket or (int(getattr(raw, "order", 0)) or None),
            "price": float(getattr(raw, "price", price) or price or 0.0),
            "volume": float(getattr(raw, "volume", volume) or volume),
            "retcode": retcode,
            "comment": str(getattr(raw, "comment", "")),
        }

    # --- endpoints ------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        mt5 = self._ensure()
        term = mt5.terminal_info()
        account = mt5.account_info()
        acc_dict: dict[str, Any] = {}
        if account is not None:
            acc_dict = {
                "login": int(getattr(account, "login", 0)),
                "balance": float(getattr(account, "balance", 0.0)),
                "equity": float(getattr(account, "equity", 0.0)),
                "profit": float(getattr(account, "profit", 0.0)),
                "margin": float(getattr(account, "margin", 0.0)),
                "margin_free": float(getattr(account, "margin_free", 0.0)),
                "server": str(getattr(account, "server", "")),
                "currency": str(getattr(account, "currency", "")),
            }
        return {
            "status": "ok",
            "connected": term is not None,
            "trade_allowed": bool(getattr(term, "trade_allowed", False)),
            "server": self.s.mt5_server,
            "login": int(account.login) if account is not None else None,
            "symbol": self.s.mt5_symbol,
            "account": acc_dict,
        }

    def tick(self, symbol: str) -> dict[str, Any]:
        mt5 = self._ensure()
        self._select(mt5, symbol)
        t = mt5.symbol_info_tick(symbol)
        if t is None:
            raise BridgeError(f"no tick for {symbol}: {mt5.last_error()}")
        return {
            "time": datetime.fromtimestamp(t.time, tz=UTC).isoformat(),
            "bid": float(t.bid),
            "ask": float(t.ask),
        }

    def _parse_dt(self, val: str) -> datetime:
        s = val.replace("Z", "").split("+")[0]
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")

    def rates(self, symbol: str, timeframe: str, start: str, end: str) -> dict[str, Any]:
        mt5 = self._ensure()
        self._select(mt5, symbol)
        dt_start = self._parse_dt(start)
        dt_end = self._parse_dt(end)
        rows = mt5.copy_rates_range(symbol, self._tf(mt5, timeframe), dt_start, dt_end)
        if rows is None:
            raise BridgeError(f"copy_rates_range failed: {mt5.last_error()}")
        candles = [
            {
                "time": datetime.fromtimestamp(int(r["time"]), tz=UTC).isoformat(),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["tick_volume"]),
                "spread": float(r["spread"]),
            }
            for r in rows
        ]
        return {"candles": candles}

    def order(self, payload: dict[str, Any]) -> dict[str, Any]:
        mt5 = self._ensure()
        symbol = str(payload["symbol"])
        self._select(mt5, symbol)
        is_buy = str(payload["side"]).upper() == "BUY"
        volume = float(payload["volume"])
        price = payload.get("price")
        order_type = str(payload.get("order_type", "market"))
        if price in (None, 0) or order_type == "market":
            t = mt5.symbol_info_tick(symbol)
            if t is None:
                raise BridgeError(f"no tick for {symbol}")
            price = float(t.ask if is_buy else t.bid)
            action = mt5.TRADE_ACTION_DEAL
            mt5_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        else:
            action = mt5.TRADE_ACTION_PENDING
            mt5_type = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT
        req: dict[str, Any] = {
            "action": action,
            "symbol": symbol,
            "volume": volume,
            "type": mt5_type,
            "price": float(price),
            "deviation": int(payload.get("deviation", self.s.mt5_deviation)),
            "magic": int(payload.get("magic", 0)),
            "comment": str(payload.get("comment", "goldscalper")),
            "type_filling": self._filling(mt5),
        }
        if payload.get("sl") is not None:
            req["sl"] = float(payload["sl"])
        if payload.get("tp") is not None:
            req["tp"] = float(payload["tp"])
        if action == mt5.TRADE_ACTION_PENDING:
            req["type_time"] = mt5.ORDER_TIME_GTC
        raw = mt5.order_send(req)
        return self._result(mt5, raw, price=float(price), volume=volume)

    def positions(self, symbol: str | None) -> dict[str, Any]:
        mt5 = self._ensure()
        raw = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        out = []
        for p in raw or []:
            out.append(
                {
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                    "volume": float(p.volume),
                    "price_open": float(p.price_open),
                    "sl": float(p.sl) or None,
                    "tp": float(p.tp) or None,
                    "price_current": float(p.price_current),
                    "profit": float(p.profit),
                    "magic": p.magic,
                }
            )
        return {"positions": out}

    def close(
        self, ticket: int, price: float | None, volume: float | None
    ) -> dict[str, Any]:
        mt5 = self._ensure()
        current = [p for p in (mt5.positions_get() or []) if int(p.ticket) == ticket]
        if not current:
            return {
                "ok": False, "ticket": ticket, "price": None, "volume": 0.0,
                "retcode": -1, "comment": "position not found",
            }
        pos = current[0]
        is_long = pos.type == mt5.POSITION_TYPE_BUY
        t = mt5.symbol_info_tick(pos.symbol)
        if t is None:
            raise BridgeError("no tick for close")
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": pos.symbol,
            "volume": float(volume or pos.volume),
            "type": mt5.ORDER_TYPE_SELL if is_long else mt5.ORDER_TYPE_BUY,
            "price": float(t.bid if is_long else t.ask),
            "deviation": int(self.s.mt5_deviation),
            "magic": int(pos.magic),
            "type_filling": self._filling(mt5),
            "comment": "close",
        }
        raw = mt5.order_send(req)
        return self._result(mt5, raw, ticket=ticket, price=float(req["price"]),
                            volume=float(req["volume"]))

    def modify(self, ticket: int, sl: float | None, tp: float | None) -> dict[str, Any]:
        mt5 = self._ensure()
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl": float(sl) if sl is not None else 0.0,
            "tp": float(tp) if tp is not None else 0.0,
        }
        raw = mt5.order_send(req)
        return self._result(mt5, raw, ticket=ticket)


__all__ = ["BridgeBackend", "BridgeError", "MT5Backend"]
