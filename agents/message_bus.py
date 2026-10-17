"""Inter-agent message bus.

Two implementations share a minimal interface (:class:`Bus`):

* :class:`MemoryBus` — in-process, for tests and single-process runs.
* :class:`MessageBus` — Redis Streams, for cross-process / scalable deployments.

Payloads are plain dicts; values are serialized to JSON strings for Redis.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Protocol

_logger = logging.getLogger(__name__)

try:  # optional at import-time; only MessageBus needs it
    import orjson as _json

    def _dumps(obj: Any) -> str:
        return _json.dumps(obj).decode("utf-8")

    def _loads(raw: Any) -> Any:
        if isinstance(raw, bytes):
            return _json.loads(raw)
        if isinstance(raw, str):
            return _json.loads(raw.encode("utf-8"))
        return raw

except Exception:  # pragma: no cover
    import json as _json  # type: ignore

    def _dumps(obj: Any) -> str:
        return _json.dumps(obj)

    def _loads(raw: Any) -> Any:
        return _json.loads(raw)


class Bus(Protocol):
    """Minimal publish/subscribe interface used by agents and orchestrator."""

    async def publish(self, stream: str, data: dict[str, Any]) -> None: ...
    async def close(self) -> None: ...


class MemoryBus:
    """In-process bus that buffers published payloads per stream."""

    def __init__(self, maxlen: int = 10_000) -> None:
        self.maxlen = maxlen
        self.streams: dict[str, list[dict[str, Any]]] = defaultdict(list)

    async def publish(self, stream: str, data: dict[str, Any]) -> None:
        buf = self.streams[stream]
        buf.append(data)
        if len(buf) > self.maxlen:
            del buf[: len(buf) - self.maxlen]

    async def close(self) -> None:  # pragma: no cover - nothing to close
        return None

    # test helpers
    def messages(self, stream: str) -> list[dict[str, Any]]:
        return list(self.streams.get(stream, []))


class MessageBus:
    """Redis Streams-backed bus.

    Uses XADD for publish and consumer groups for reliable processing. The
    Redis client is created lazily so importing this module never requires a
    live connection.
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        redis_url: str | None = None,
        maxlen: int = 10_000,
    ) -> None:
        self._client = redis_client
        self._redis_url = redis_url
        self.maxlen = maxlen

    def _client_or_create(self) -> Any:
        if self._client is None:
            import redis.asyncio as aioredis

            from config.settings import settings

            self._client = aioredis.from_url(
                self._redis_url or settings.redis_url, decode_responses=True
            )
        return self._client

    async def publish(self, stream: str, data: dict[str, Any]) -> None:
        client = self._client_or_create()
        await client.xadd(
            stream,
            {"data": _dumps(data)},
            maxlen=self.maxlen,
            approximate=True,
        )

    async def ensure_group(self, stream: str, group: str) -> None:
        client = self._client_or_create()
        try:
            await client.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception as exc:  # noqa: BLE001 - BUSYGROUP expected on re-run
            if "BUSYGROUP" not in str(exc):
                raise

    async def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 100,
        block_ms: int = 1000,
    ) -> list[tuple[str, dict[str, Any]]]:
        client = self._client_or_create()
        resp = await client.xreadgroup(
            group, consumer, {stream: ">"}, count=count, block=block_ms
        )
        out: list[tuple[str, dict[str, Any]]] = []
        for _stream, entries in resp or []:
            for entry_id, fields in entries:
                out.append((entry_id, _loads(fields.get("data", "{}"))))
        return out

    async def ack(self, stream: str, group: str, *ids: str) -> None:
        if not ids:
            return
        client = self._client_or_create()
        await client.xack(stream, group, *ids)

    async def close(self) -> None:
        client = self._client
        if client is not None:
            try:
                await client.aclose()
            except Exception as exc:  # noqa: BLE001
                _logger.debug("redis close failed: %s", exc)
            self._client = None


def now_ms() -> int:
    """Convenience: current epoch milliseconds (used in event payloads)."""
    return int(time.time() * 1000)
