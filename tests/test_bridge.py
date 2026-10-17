"""Contract tests for the MT5 HTTP bridge.

The tests inject a fake :class:`bridge.backend.BridgeBackend` so they run
on Linux without the MetaTrader5 terminal installed.

They also exercise :class:`core.mt5_connector.BridgeMT5Client` against the
fake backend served via ASGI to verify the HTTP contract matches.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from bridge.app import create_bridge_app
from bridge.backend import BridgeBackend
from core.mt5_connector import (
    SIDE_BUY,
    SIDE_SELL,
    BridgeMT5Client,
    OrderRequest,
)


class FakeBackend(BridgeBackend):
    def __init__(self) -> None:
        self._pos: dict[int, dict[str, Any]] = {}
        self._tick_counter = 0

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "connected": True, "server": "Fake", "symbol": "XAUUSD"}

    def tick(self, symbol: str) -> dict[str, Any]:
        self._tick_counter += 1
        return {
            "time": datetime.now(UTC).isoformat(),
            "bid": 2350.0 + self._tick_counter * 0.01,
            "ask": 2350.05 + self._tick_counter * 0.01,
        }

    def rates(self, symbol: str, timeframe: str, start: str, end: str) -> dict[str, Any]:
        s = datetime.fromisoformat(start)
        candles = []
        price = 2350.0
        cur = int(s.timestamp()) - (int(s.timestamp()) % 60)
        for _ in range(5):
            o = price
            h = o + 0.2
            low = o - 0.1
            c = o + 0.05
            candles.append(
                {
                    "time": datetime.fromtimestamp(cur, tz=UTC).isoformat(),
                    "open": o,
                    "high": h,
                    "low": low,
                    "close": c,
                    "volume": 50.0,
                    "spread": 2.0,
                }
            )
            price = c
            cur += 60
        return {"candles": candles}

    def order(self, payload: dict[str, Any]) -> dict[str, Any]:
        ticket = 200000 + len(self._pos) + 1
        side = str(payload["side"]).upper()
        price = float(payload.get("price") or 2350.0)
        vol = float(payload["volume"])
        self._pos[ticket] = {
            "ticket": ticket,
            "symbol": payload["symbol"],
            "side": side,
            "volume": vol,
            "price_open": price,
            "sl": payload.get("sl"),
            "tp": payload.get("tp"),
            "price_current": price,
            "profit": 0.0,
            "magic": payload.get("magic", 0),
        }
        return {
            "ok": True,
            "ticket": ticket,
            "price": price,
            "volume": vol,
            "retcode": 10009,
            "comment": "mock",
        }

    def positions(self, symbol: str | None) -> dict[str, Any]:
        items = list(self._pos.values())
        if symbol:
            items = [p for p in items if p["symbol"] == symbol]
        return {"positions": items}

    def close(
        self, ticket: int, price: float | None, volume: float | None
    ) -> dict[str, Any]:
        pos = self._pos.pop(ticket, None)
        if not pos:
            return {
                "ok": False,
                "ticket": ticket,
                "price": price,
                "volume": volume or 0.0,
                "retcode": -1,
                "comment": "not found",
            }
        close_price = price if price is not None else 2350.01
        close_vol = volume if volume is not None else pos["volume"]
        return {
            "ok": True,
            "ticket": ticket,
            "price": close_price,
            "volume": close_vol,
            "retcode": 10009,
            "comment": "mock close",
        }

    def modify(self, ticket: int, sl: float | None, tp: float | None) -> dict[str, Any]:
        pos = self._pos.get(ticket)
        if not pos:
            return {
                "ok": False,
                "ticket": ticket,
                "price": None,
                "volume": 0.0,
                "retcode": -1,
                "comment": "not found",
            }
        if sl is not None:
            pos["sl"] = sl
        if tp is not None:
            pos["tp"] = tp
        return {"ok": True, "ticket": ticket, "retcode": 10009, "comment": "mock mod"}


@pytest.fixture
def app():
    backend = FakeBackend()
    return create_bridge_app(backend=backend, token="t0k3n")


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://bridge"
    ) as c:
        yield c


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer t0k3n"}


async def test_health_no_auth_ok(client: httpx.AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_tick_requires_auth(client: httpx.AsyncClient):
    r = await client.get("/tick", params={"symbol": "XAUUSD"})
    assert r.status_code == 401
    r2 = await client.get("/tick", params={"symbol": "XAUUSD"}, headers=auth())
    assert r2.status_code == 200
    j = r2.json()
    assert "bid" in j and "ask" in j


async def test_rates_contract(client: httpx.AsyncClient):
    start = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    end = datetime.now(UTC).isoformat()
    r = await client.get(
        "/rates",
        params={"symbol": "XAUUSD", "timeframe": "M1", "start": start, "end": end},
        headers=auth(),
    )
    assert r.status_code == 200
    candles = r.json()["candles"]
    assert len(candles) == 5
    assert all(k in candles[0] for k in ("time", "open", "high", "low", "close"))


async def test_order_positions_close_modify(client: httpx.AsyncClient):
    r = await client.post(
        "/order",
        json={
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 0.10,
            "sl": 2348.0,
            "tp": 2352.0,
        },
        headers=auth(),
    )
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["ticket"] is not None

    pos = await client.get("/positions", headers=auth())
    assert pos.status_code == 200
    assert len(pos.json()["positions"]) == 1

    close = await client.post(
        "/close",
        json={"ticket": j["ticket"], "volume": 0.10},
        headers=auth(),
    )
    assert close.status_code == 200
    assert close.json()["ok"] is True

    # re-open and modify
    r2 = await client.post(
        "/order", json={"symbol": "XAUUSD", "side": "SELL", "volume": 0.05}, headers=auth()
    )
    tid = r2.json()["ticket"]
    mod = await client.post(
        "/modify", json={"ticket": tid, "sl": 2351.0, "tp": 2347.5}, headers=auth()
    )
    assert mod.status_code == 200
    assert mod.json()["ok"] is True


async def test_bridge_client_roundtrip():
    backend = FakeBackend()
    app = create_bridge_app(backend=backend, token="t0k3n")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://bridge",
        headers=auth(),
    ) as http:
        c = BridgeMT5Client(base_url="http://bridge", token="t0k3n", client=http)
        assert await c.connect()
        q = await c.symbol_tick("XAUUSD")
        assert q.bid > 0

        s = datetime.now(UTC) - timedelta(minutes=1)
        e = datetime.now(UTC)
        rates = await c.copy_rates("XAUUSD", "M1", s, e)
        assert len(rates) == 5

        res = await c.order_send(
            OrderRequest(symbol="XAUUSD", side=SIDE_BUY, volume=0.20, sl=2349.0, tp=2351.0)
        )
        assert res.ok and res.ticket

        poses = await c.positions()
        assert len(poses) == 1

        cls = await c.close_position(res.ticket, volume=0.10)
        assert cls.ok

        # second order
        res2 = await c.order_send(
            OrderRequest(symbol="XAUUSD", side=SIDE_SELL, volume=0.10)
        )
        mod = await c.modify_position(res2.ticket, sl=2351.1, tp=2349.9)
        assert mod.ok
        await c.disconnect()
