"""WebSocket connection manager for telemetry broadcast.

Tracks active clients and fans out JSON payloads. Used by the orchestrator and
API routes to push real-time state to the PWA frontend.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket

from config.logging import get_logger

log = get_logger("api.ws")


class ConnectionManager:
    """Manage active WebSocket connections safely under concurrency."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
        log.info("client connected (total=%d)", self.count)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)
        log.info("client disconnected (total=%d)", self.count)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Send a JSON payload to all clients, pruning dead connections."""
        async with self._lock:
            targets = list(self._clients)

        if not targets:
            return

        import json

        try:
            text = json.dumps(payload, default=str)
        except Exception as exc:  # noqa: BLE001
            log.warning("ws payload serialization error: %r", exc)
            return

        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception as exc:  # noqa: BLE001
                log.warning("ws send_text error: %r", exc)
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)
            log.info("pruned %d dead connections (active=%d)", len(dead), len(self._clients))


manager = ConnectionManager()
