-- =============================================================================
-- GoldScalper — 004 multi-user authentication & MT5 trading accounts
-- Target: TimescaleDB / PostgreSQL 16
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user', 'operator')),
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);

CREATE TABLE IF NOT EXISTS user_trading_accounts (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    broker         TEXT NOT NULL DEFAULT 'Exness',
    mt5_login      BIGINT NOT NULL,
    mt5_password   TEXT NOT NULL,
    mt5_server     TEXT NOT NULL DEFAULT 'Exness-MT5Trial7',
    risk_lot_mode  TEXT NOT NULL DEFAULT 'fixed' CHECK (risk_lot_mode IN ('fixed', 'compound', 'auto')),
    lot_size       DOUBLE PRECISION NOT NULL DEFAULT 0.01,
    is_active      BOOLEAN NOT NULL DEFAULT true,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_user_mt5 UNIQUE(user_id, mt5_login)
);

CREATE INDEX IF NOT EXISTS idx_user_trading_accounts_user ON user_trading_accounts (user_id);
