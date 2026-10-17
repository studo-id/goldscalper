"""FastAPI bridge app exposed to the Linux bot over HTTP.

Run on the Windows MT5 host:

    uvicorn bridge.app:app --host 0.0.0.0 --port 9095
    # or
    python -m bridge.run
"""

from __future__ import annotations

import hmac
import sys
if sys.platform == "win32":
    import asyncio
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from bridge.backend import BridgeBackend, BridgeError, MT5Backend
from bridge.config import BridgeSettings

BRIDGE_VERSION = "0.1.0"


class OrderPayload(BaseModel):
    symbol: str
    side: str = Field(pattern="^(BUY|SELL|buy|sell)$")
    volume: float = Field(gt=0)
    price: float | None = None
    sl: float | None = None
    tp: float | None = None
    magic: int = 0
    deviation: int = 20
    comment: str = ""
    order_type: str = "market"


class ClosePayload(BaseModel):
    ticket: int
    price: float | None = None
    volume: float | None = None


class ModifyPayload(BaseModel):
    ticket: int
    sl: float | None = None
    tp: float | None = None


def create_bridge_app(
    backend: BridgeBackend | None = None,
    settings: BridgeSettings | None = None,
    token: str | None = None,
) -> FastAPI:
    cfg = settings or BridgeSettings()
    resolved_token = token if token is not None else cfg.bridge_token
    active_backend = backend or MT5Backend(cfg)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        shutdown = getattr(active_backend, "shutdown", None)
        if callable(shutdown):
            shutdown()

    app = FastAPI(
        title="GoldScalper MT5 Bridge", version=BRIDGE_VERSION, lifespan=lifespan
    )
    app.state.settings = cfg
    app.state.backend = active_backend
    app.state.token = resolved_token

    def require_token(authorization: str | None = Header(default=None)) -> None:
        if not app.state.token:
            return  # open bridge (dev); keep it on a trusted network only
        presented = ""
        if authorization and authorization.lower().startswith("bearer "):
            presented = authorization[7:].strip()
        if not hmac.compare_digest(presented, app.state.token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bridge token"
            )

    def backend_of(request: Request) -> BridgeBackend:
        return request.app.state.backend

    def _run(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except BridgeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        try:
            return _run(backend_of(request).health)
        except HTTPException:
            return {"status": "degraded", "connected": False, "server": cfg.mt5_server}

    @app.get("/tick", dependencies=[Depends(require_token)])
    async def tick(request: Request, symbol: str = Query(...)) -> dict[str, Any]:
        return _run(backend_of(request).tick, symbol)

    @app.get("/rates", dependencies=[Depends(require_token)])
    async def rates(
        request: Request,
        symbol: str = Query(...),
        timeframe: str = Query(...),
        start: str = Query(...),
        end: str = Query(...),
    ) -> dict[str, Any]:
        return _run(backend_of(request).rates, symbol, timeframe, start, end)

    @app.post("/order", dependencies=[Depends(require_token)])
    async def order(request: Request, payload: OrderPayload) -> dict[str, Any]:
        return _run(backend_of(request).order, payload.model_dump())

    @app.get("/positions", dependencies=[Depends(require_token)])
    async def positions(
        request: Request, symbol: str | None = Query(default=None)
    ) -> dict[str, Any]:
        return _run(backend_of(request).positions, symbol)

    @app.post("/close", dependencies=[Depends(require_token)])
    async def close(request: Request, payload: ClosePayload) -> dict[str, Any]:
        return _run(
            backend_of(request).close, payload.ticket, payload.price, payload.volume
        )

    @app.post("/modify", dependencies=[Depends(require_token)])
    async def modify(request: Request, payload: ModifyPayload) -> dict[str, Any]:
        return _run(backend_of(request).modify, payload.ticket, payload.sl, payload.tp)

    return app


app = create_bridge_app()

__all__ = ["app", "create_bridge_app"]
