"""GoldScalper configuration.

Central settings loaded from environment / .env via pydantic-settings.
AcengGold is a read-only reference system — nothing here imports from it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings.

    Values are sourced (in priority order) from: process env, then `.env`.
    Nested env vars use the `__` delimiter, e.g. `DB__HOST`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
        # Deliver raw strings for complex fields (e.g. comma-separated lists)
        # to the validators below instead of attempting JSON decoding.
        enable_decoding=False,
    )

    # --- App ---
    app_name: str = "GoldScalper"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False

    # --- API server ---
    host: str = "0.0.0.0"
    port: int = 9090
    api_token: str = Field(default="change_me", description="Bearer token for API/WS auth")
    cors_origins: list[str] = Field(default_factory=list)

    # --- Runtime (live agent loop + execution) ---
    runtime_enabled: bool = True

    # --- Database (TimescaleDB / PostgreSQL) ---
    db_host: str = "localhost"
    db_port: int = 5433
    db_user: str = "goldscalper"
    db_password: str = "change_me_in_env"  # noqa: S105 - placeholder, overridden by .env
    db_name: str = "goldscalper"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # --- Redis (message bus) ---
    redis_host: str = "localhost"
    redis_port: int = 6380
    redis_db: int = 0
    redis_password: str | None = None

    # --- MT5 broker (EXNESS demo) ---
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = "Exness-Real10"
    mt5_path: str = ""
    mt5_symbol: str = "XAUUSD"
    mt5_magic: int = 990001
    mt5_deviation: int = 20
    mt5_mock: bool = True

    # --- Remote MT5 bridge (Windows host running the terminal) ---
    mt5_bridge_url: str = ""
    mt5_bridge_token: str = ""

    # --- Telegram notifications ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_enabled: bool = False

    # --- Trading / risk (fast scalper defaults - Small Capital Sprint) ---
    risk_per_trade_pct: float = 0.5
    max_daily_loss_pct: float = 15.0       # Sprint mode hard daily loss limit
    max_weekly_loss_pct: float = 25.0
    max_consecutive_losses: int = 3        # Aligned with institutional SOP (3 consecutive losses -> halt)
    max_spread_points: int = 45
    max_open_positions: int = 3            # Small-capital sprint: Max 3 positions concurrently
    default_rr: float = 1.5
    atr_sl_multiplier: float = 1.2
    max_hold_seconds: int = 600            # Max 10 mins hold per position
    cycle_interval_ms: int = 1000

    # --- Institutional SMC & Session Disciplines (Top-Down, OB, News & Session Clocks) ---
    news_blackout_pre_minutes: int = 30       # 30 mins before high-impact news release
    news_blackout_post_minutes: int = 20      # 20 mins after high-impact news release
    london_open_freeze_enabled: bool = True   # Freeze new orders 08:00-08:15 UTC (observation phase)
    hard_cutoff_utc_enabled: bool = False      # Hard cutoff on new entries starting 15:30 UTC (default False for active sprint)
    overnight_flat_utc_enabled: bool = True   # Flag open intraday trades for flat exit before 21:00 UTC
    d1_macro_bias_veto_enabled: bool = True   # Veto opposing trades when D1 Macro has clear confirmed trend

    # --- Micro-SR & Anti-Chasing Veto (M1 Confirmation Range) ---
    micro_sr_veto_enabled: bool = True
    micro_sr_lookback_m1: int = 20           # 20 bars M1 = 20 minutes local swing window
    micro_sr_confirm_range_usd: float = 1.20 # Variable confirmation range buffer ($1.20 = 12 pips buffer)

    # --- Execution / instrument ---
    contract_size: float = 100.0  # XAUUSD: 1.0 lot = 100 troy oz
    commission_per_lot: float = 7.0
    min_lot: float = 0.01
    max_lot: float = 50.0
    lot_step: float = 0.01

    # --- Position management ---
    trailing_enabled: bool = True
    breakeven_at_r: float = 1.0  # move SL to entry once profit >= 1R
    trailing_atr_mult: float = 1.0
    partial_tp_at_r: float = 1.0  # take partial profit at 1R
    partial_tp_pct: float = 50.0

    # --- Scalper Time-Decay & Stagnation Harvest ---
    stagnant_harvest_enabled: bool = True
    stagnant_harvest_seconds: int = 120       # 2 minutes: harvest if profit >= $2.50
    stagnant_min_profit_usd: float = 2.50     # minimum USD profit to harvest stalled trade (covers spread & commission)
    stagnant_time_decay_seconds: int = 300    # 5 minutes: harvest on any profit >= $1.50

    # --- The Juggler: Anti-Bleeding Hard Clamp & Circuit Breaker ---
    juggler_enabled: bool = True
    hard_loss_clamp_enabled: bool = True
    hard_loss_clamp_usd: float = 7.00        # Max floating loss per trade before force-cut (1.2x avg win)
    loss_time_decay_seconds: int = 180       # Max seconds negative position can float without reversing
    loss_time_decay_min_loss_usd: float = 2.00  # Min loss to trigger loss time-decay cut
    daily_profit_target_pct: float = 35.0    # Daily sprint profit target (30-40%)
    daily_profit_lock_enabled: bool = True   # Circuit breaker: freeze all orders when daily target reached
    daily_loss_limit_pct: float = 15.0       # Hard shutdown when daily loss hits -15%
    lot_sizing_mode: str = "TARGET_SEEKING"  # "FIXED" | "ATR_RISK" | "TARGET_SEEKING"
    target_seeking_swing_usd: float = 3.00   # Estimated swing USD per trade for target-seeking sizing
    max_scalper_lot: float = 0.08            # Hard cap lot for fast scalper sprint to prevent outsized loss

    # --- Multi-Timeframe Watchdog (Satpam Bertingkat M1, M5, M15) ---
    watchdog_enabled: bool = True
    watchdog_min_hold_seconds: int = 60         # 1 full M1 candle (60s) breathing room before early cut
    watchdog_time_extension_seconds: int = 300  # Up to +5 mins extension if M5/HTF supporting
    watchdog_early_invalidation_enabled: bool = True
    watchdog_early_loss_ratio: float = 0.40     # Cut loss early at 40% of clamp if M1+M5 adverse
    fast_breakeven_pips: float = 12.0           # Scalper BE lock distance (pips on XAUUSD)

    # --- Micro S/R & M1 Anti-Chasing Dead Zone Protection ---
    micro_sr_veto_enabled: bool = True
    micro_sr_lookback_m1: int = 20
    micro_sr_confirm_range_usd: float = 1.20
    micro_sr_dead_zone_enabled: bool = True
    micro_sr_dead_zone_max_span: float = 12.00  # Max M1 span (USD) to enforce 30/40/30 dead zone

    # --- BizDev: Rebate & Friction Engine ---
    bizdev_enabled: bool = True
    rebate_per_lot_usd: float = 6.00         # Estimated IB rebate per lot on XAUUSD
    max_friction_ratio_pct: float = 25.0     # Max friction threshold: (spread+slip)/gross_profit

    # --- Multi-Entry & Rescue Recovery Mode (GANAS CERDAS) ---
    multi_entry_enabled: bool = True
    rescue_mode_enabled: bool = True
    rescue_max_layers: int = 2              # Strict Cap: Max 2 positions per side (1 Initial + 1 Rescue)
    rescue_min_distance_pips: float = 20.0  # 20 pips = 2.00 USD on Gold
    rescue_score_threshold: float = 1.60
    rescue_multiplier: float = 1.0          # Flat lot: no dangerous Martingale lot ballooning
    basket_tp_buffer_pips: float = 3.0      # Fast recovery buffer above avg BE price
    basket_trailing_enabled: bool = True    # Dynamic trailing basket exit
    basket_trail_step_usd: float = 0.50     # Trail $0.50 behind peak profit when exploding
    predator_reload_enabled: bool = False   # Disabled blind reload to prevent peak entry traps
    predator_reload_window_s: int = 6       # 6-second reload boost window
    risk_free_pyramiding: bool = True       # Lock existing layer SL into profit when scaling

    # --- Learning loop ---
    learning_enabled: bool = True
    bandit_exploration: float = 0.1
    min_trades_for_weight_update: int = 30
    weight_max_delta_pct: float = 20.0

    # --- Paths ---
    docs_dir: str = "docs"
    data_dir: str = "data"
    frontend_dir: str = "frontend"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v: object) -> object:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    # --- Derived ---
    @property
    def db_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def db_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()
