"""Bridge-side settings (Windows MT5 host).

Reads the same env var names as the bot for MT5 credentials so a single
``.env`` can be reused, plus ``BRIDGE_*`` for the bridge server itself.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BridgeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- bridge server ---
    bridge_host: str = "0.0.0.0"
    bridge_port: int = 9095
    bridge_token: str = ""
    bridge_log_level: str = "info"

    # --- MT5 terminal ---
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = "Exness-Real10"
    mt5_path: str = ""
    mt5_symbol: str = "XAUUSD"
    mt5_deviation: int = 20
    mt5_filling: str = "IOC"  # IOC | FOK | RETURN
    mt5_rpyc_host: str = "mt5"
    mt5_rpyc_port: int = 8001


__all__ = ["BridgeSettings"]
