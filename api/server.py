"""FastAPI application factory & lifespan wiring."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import agents, auth_routes, bizdev, control, health, lessons, market, performance, trades
from api.ws_manager import manager
from config.logging import configure_logging, get_logger
from config.settings import settings
from data import db, redis_client

log = get_logger("api.server")


async def _telemetry_pump(runtime) -> None:
    """Periodically broadcast a lightweight runtime snapshot to WS clients."""
    last_bid: float | None = None
    last_ask: float | None = None
    last_cycles: int | None = None
    last_send = 0.0

    while True:
        try:
            await asyncio.sleep(0.08)
            if manager.count and runtime is not None:
                loop = asyncio.get_event_loop()
                now = loop.time()
                t = runtime.telemetry()
                bid = t.get("bid")
                ask = t.get("ask")
                cycles = t.get("cycles")
                if bid != last_bid or ask != last_ask or cycles != last_cycles or (now - last_send >= 1.0):
                    last_bid = bid
                    last_ask = ask
                    last_cycles = cycles
                    last_send = now
                    await manager.broadcast({"type": "telemetry", "data": t})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.debug("telemetry pump error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("starting %s (%s)", settings.app_name, settings.environment)

    runtime = None
    pump: asyncio.Task | None = None
    if settings.runtime_enabled:
        try:
            from runtime import Runtime

            runtime = Runtime(settings)
            await runtime.start()
            pump = asyncio.create_task(_telemetry_pump(runtime), name="gs-telemetry")
            log.info("runtime started (%d agents)", runtime.registry.size)
        except Exception as exc:  # noqa: BLE001 - API must boot even if runtime fails
            log.error("runtime failed to start: %s", exc)
            runtime = None
    app.state.runtime = runtime

    yield

    if pump is not None:
        pump.cancel()
    if runtime is not None:
        try:
            await runtime.stop()
        except Exception as exc:  # noqa: BLE001
            log.warning("runtime stop failed: %s", exc)
    log.info("shutting down %s", settings.app_name)
    await db.dispose_engine()
    await redis_client.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Unauthenticated health and auth routes.
    app.include_router(health.router)
    app.include_router(auth_routes.router)
    # Authenticated control/telemetry/data routes.
    app.include_router(control.router)
    app.include_router(agents.router)
    app.include_router(trades.router)
    app.include_router(lessons.router)
    app.include_router(performance.router)
    app.include_router(market.router)
    app.include_router(bizdev.router)

    @app.get("/api/ping")
    async def ping() -> JSONResponse:
        return JSONResponse({"pong": True, "clients": manager.count})

    @app.websocket("/ws/telemetry")
    async def telemetry_ws(websocket: WebSocket) -> None:
        # Reject unauthenticated clients before accepting the socket.
        from api.auth import _matches  # local import: internal helper

        token = websocket.query_params.get("token")
        if not _matches(token):
            await websocket.close(code=4401)
            return

        await manager.connect(websocket)
        runtime = getattr(websocket.app.state, "runtime", None)
        if runtime is not None:
            try:
                await websocket.send_json({"type": "telemetry", "data": runtime.telemetry()})
            except Exception as exc:  # noqa: BLE001
                log.debug("initial telemetry send failed: %s", exc)
        try:
            while True:
                # Keep the socket open; ignore inbound (client is a listener).
                await websocket.receive_text()
        except WebSocketDisconnect:
            await manager.disconnect(websocket)
        except Exception:  # noqa: BLE001
            await manager.disconnect(websocket)

    class NoCacheStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope):
            response = await super().get_response(path, scope)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

    frontend_dir = Path(settings.frontend_dir)
    if frontend_dir.exists():
        app.mount("/", NoCacheStaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_app()
