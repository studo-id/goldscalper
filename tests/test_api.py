"""API route tests (in-process, fake runtime, no DB)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from api.server import app
from config.settings import settings


@dataclass
class FakeAgent:
    id: str
    division: str


@dataclass
class FakePatterns:
    def top(self, n: int = 5) -> list[dict]:
        return [{"regime": "range", "root_cause": "adverse_move", "count": 3, "winrate": 0.0}]

    def worst(self, n: int = 5) -> list[dict]:
        return self.top(n)


@dataclass
class FakeOrchestrator:
    last_decision: Any = None
    cycle_count: int = 0
    lesson_repo: Any = None
    votes: list = field(default_factory=list)


@dataclass
class FakeOrderManager:
    trade_repo: Any = None


@dataclass
class FakeCandle:
    symbol: str
    timeframe: str
    time: Any
    open: float
    high: float
    low: float
    close: float
    volume: float = 100.0


class FakeCache:
    def __init__(self, candles: list | None = None) -> None:
        self._candles = candles or []

    def latest(self, symbol: str, timeframe: str, n: int = 1) -> list:
        return self._candles[-n:]


class FakeClient:
    async def copy_rates(self, symbol: str, timeframe: str, start: Any, end: Any) -> list:
        from datetime import UTC, datetime
        return [
            FakeCandle(
                symbol=symbol,
                timeframe=timeframe,
                time=datetime.now(UTC),
                open=2400.0,
                high=2405.0,
                low=2395.0,
                close=2402.0,
                volume=50.0,
            )
        ]


@dataclass
class FakeRuntime:
    registry: Any
    orchestrator: Any = field(default_factory=FakeOrchestrator)
    patterns: Any = field(default_factory=FakePatterns)
    order_manager: Any = field(default_factory=FakeOrderManager)
    paused: bool = False
    symbol: str = "XAUUSD"
    cache: Any = field(default_factory=FakeCache)
    client: Any = field(default_factory=FakeClient)
    _trades: dict = field(default_factory=dict)
    panicked: int = 0
    manual: dict | None = None

    def snapshot(self) -> dict:
        return {"running": True, "paused": self.paused, "symbol": "XAUUSD", "agents": 37}

    def agent_health(self) -> list[dict]:
        return [{"id": a.id, "division": a.division, "weight": 1.0} for a in self.registry.all()]

    async def close_single_position(self, ticket: int) -> bool:
        return ticket == 12345

    async def panic_close(self) -> int:
        self.panicked += 1
        return 2

    async def manual_order(self, side: str, size: float, sl=None, tp=None) -> dict:
        self.manual = {"side": side, "size": size}
        return {"ok": True, "ticket": 1, "price": 2350.0}


class FakeRegistry:
    def all(self) -> list[FakeAgent]:
        return [
            FakeAgent("TF-M1-Sniper", "timeframe"),
            FakeAgent("TF-H1-Regime", "timeframe"),
            FakeAgent("Risk-PositionSizer", "risk"),
        ]


@pytest.fixture
def client() -> httpx.AsyncClient:
    app.state.runtime = FakeRuntime(registry=FakeRegistry())
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.api_token}"}


async def test_status_requires_token() -> None:
    app.state.runtime = FakeRuntime(registry=FakeRegistry())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/status")
    assert resp.status_code == 401


async def test_status_ok(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/status", headers=auth())
    assert resp.status_code == 200
    assert resp.json()["agents"] == 37


async def test_agents_and_divisions(client: httpx.AsyncClient) -> None:
    async with client as c:
        a = await c.get("/api/agents", headers=auth())
        d = await c.get("/api/agents/divisions", headers=auth())
    assert len(a.json()["agents"]) == 3
    divs = d.json()["divisions"]
    assert divs["timeframe"]["agents"] == 2
    assert divs["risk"]["agents"] == 1


async def test_spk_latest(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/spk/latest", headers=auth())
    assert resp.status_code == 200
    assert resp.json()["decision"] is None


async def test_trades_live_fallback(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/trades", headers=auth())
    assert resp.json()["source"] == "live"


async def test_performance_live_fallback(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/performance", headers=auth())
    assert resp.json()["source"] == "live"


async def test_lessons_memory_fallback(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/lessons", headers=auth())
    body = resp.json()
    assert body["source"] == "memory"
    assert body["lessons"]


async def test_control_pause_resume(client: httpx.AsyncClient) -> None:
    async with client as c:
        p = await c.post("/api/control/pause", headers=auth())
        assert p.json()["paused"] is True
        r = await c.post("/api/control/resume", headers=auth())
        assert r.json()["paused"] is False


async def test_control_panic_and_manual(client: httpx.AsyncClient) -> None:
    runtime: FakeRuntime = app.state.runtime
    async with client as c:
        panic = await c.post("/api/control/panic", headers=auth())
        manual = await c.post(
            "/api/control/manual", headers=auth(), json={"side": "BUY", "size": 0.1}
        )
    assert panic.json()["closed"] == 2
    assert runtime.panicked == 1
    assert manual.json()["ok"] is True
    assert runtime.manual == {"side": "BUY", "size": 0.1}


async def test_manual_rejects_bad_side(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.post(
            "/api/control/manual", headers=auth(), json={"side": "HOLD", "size": 0.1}
        )
    assert resp.status_code == 422


async def test_candles_ok(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/candles?tf=M1&limit=50", headers=auth())
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "XAUUSD"
    assert data["timeframe"] == "M1"
    assert "candles" in data
    assert len(data["candles"]) >= 1
    candle = data["candles"][0]
    assert "open" in candle and "close" in candle and "time" in candle


async def test_candles_bad_tf(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/candles?tf=UNKNOWN", headers=auth())
    assert resp.status_code == 400


async def test_candles_with_before_cursor(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/candles?tf=M1&limit=50&before=2000000000", headers=auth())
    assert resp.status_code == 200
    data = resp.json()
    assert "candles" in data
    assert data["timeframe"] == "M1"


async def test_close_position_ok(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.post("/api/control/close?ticket=12345", headers=auth())
    assert resp.status_code == 200
    assert resp.json() == {"ticket": 12345, "closed": True}


async def test_close_position_fail(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.post("/api/control/close?ticket=99999", headers=auth())
    assert resp.status_code == 400


