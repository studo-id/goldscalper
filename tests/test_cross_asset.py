"""Tests for CrossAssetService (Synthetic DXY and Silver correlation)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from core.cross_asset import CrossAssetService
from core.mt5_connector import Quote

UTC = timezone.utc


@pytest.fixture
def mock_client() -> AsyncMock:
    client = AsyncMock()

    async def _mock_tick(symbol: str) -> Quote | None:
        quotes = {
            "EURUSDm": Quote("EURUSDm", datetime.now(UTC), 1.1200, 1.1202),
            "USDJPYm": Quote("USDJPYm", datetime.now(UTC), 155.00, 155.02),
            "GBPUSDm": Quote("GBPUSDm", datetime.now(UTC), 1.3000, 1.3002),
            "XAGUSDm": Quote("XAGUSDm", datetime.now(UTC), 30.50, 30.52),
        }
        return quotes.get(symbol)

    client.symbol_tick.side_effect = _mock_tick
    return client


@pytest.mark.asyncio
async def test_cross_asset_update_computes_dxy(mock_client: AsyncMock) -> None:
    srv = CrossAssetService(mock_client, symbol_suffix="m", poll_interval_s=0.0)
    data = await srv.update(current_session="london")

    assert data["eurusd"] == 1.1200
    assert data["usdjpy"] == 155.00
    assert data["gbpusd"] == 1.3000
    assert data["silver"] == 30.50
    assert data["dxy"] is not None
    assert data["dxy_baseline"] == data["dxy"]
    assert data["dxy_delta"] == 0.0
    assert data["silver_delta"] == 0.0


@pytest.mark.asyncio
async def test_cross_asset_session_change_resets_baseline(mock_client: AsyncMock) -> None:
    srv = CrossAssetService(mock_client, symbol_suffix="m", poll_interval_s=0.0)
    await srv.update(current_session="asia")
    initial_dxy = srv._dxy

    # Now session changes to london
    await srv.update(current_session="london")
    assert srv._current_session == "london"
    assert srv._dxy_baseline == initial_dxy
