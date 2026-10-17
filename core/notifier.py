"""Notifications (Telegram).

A thin, dependency-optional notifier. When Telegram is disabled or not
configured it becomes a no-op that only logs — so the hot path never blocks on
the network and dev/test runs stay offline.

Uses the raw Bot API via ``httpx`` (already a project dependency); no extra SDK.
"""

from __future__ import annotations

from typing import Any

from config.logging import get_logger
from config.settings import Settings
from config.settings import settings as default_settings

log = get_logger("core.notifier")

_API = "https://api.telegram.org"


class Notifier:
    """Fire-and-forget Telegram notifier."""

    def __init__(self, settings: Settings | None = None, client: Any | None = None) -> None:
        self.s = settings or default_settings
        self._client = client
        self.sent = 0

    @property
    def enabled(self) -> bool:
        return bool(
            self.s.telegram_enabled and self.s.telegram_bot_token and self.s.telegram_chat_id
        )

    async def _get_client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def send(self, text: str, *, parse_mode: str | None = "HTML") -> bool:
        """Send a message; returns True when actually delivered."""
        if not self.enabled:
            log.debug("notifier disabled; message: %s", text)
            return False
        try:
            client = await self._get_client()
            url = f"{_API}/bot{self.s.telegram_bot_token}/sendMessage"
            payload: dict[str, Any] = {"chat_id": self.s.telegram_chat_id, "text": text}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            self.sent += 1
            return True
        except Exception as exc:  # noqa: BLE001 - notifications must never raise
            log.warning("telegram send failed: %s", exc)
            return False

    async def trade_opened(self, fields: dict[str, Any]) -> bool:
        text = (
            f"<b>{fields.get('direction')}</b> {fields.get('symbol')} "
            f"{fields.get('size')} @ {fields.get('entry_price')}\n"
            f"SL {fields.get('sl')}  TP {fields.get('tp')}  "
            f"conf {fields.get('spk_confidence')}"
        )
        return await self.send(text)

    async def trade_closed(self, fields: dict[str, Any]) -> bool:
        pnl = fields.get("pnl", 0.0)
        outcome = "WIN" if pnl >= 0 else "LOSS"
        text = (
            f"<b>CLOSED {outcome}</b> {fields.get('symbol')} pnl {pnl:.2f} "
            f"({fields.get('pips', 0.0):.1f} pips)"
        )
        return await self.send(text)

    async def alert(self, text: str) -> bool:
        return await self.send(f"<b>ALERT</b> {text}")


__all__ = ["Notifier"]
