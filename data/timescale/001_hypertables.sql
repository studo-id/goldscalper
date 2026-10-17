-- =============================================================================
-- GoldScalper — 001 hypertables & core schema
-- Target: TimescaleDB (PostgreSQL 16)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- -----------------------------------------------------------------------------
-- ticks — raw bid/ask stream (short retention)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ticks (
    time        TIMESTAMPTZ       NOT NULL,
    symbol      TEXT              NOT NULL,
    bid         DOUBLE PRECISION  NOT NULL,
    ask         DOUBLE PRECISION  NOT NULL,
    volume      DOUBLE PRECISION  NOT NULL DEFAULT 0,
    spread      DOUBLE PRECISION  NOT NULL DEFAULT 0
);
SELECT create_hypertable('ticks', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time ON ticks (symbol, time DESC);

-- -----------------------------------------------------------------------------
-- ohlcv — aggregated candles (long retention)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ohlcv (
    time        TIMESTAMPTZ       NOT NULL,
    symbol      TEXT              NOT NULL,
    timeframe   TEXT              NOT NULL,
    open        DOUBLE PRECISION  NOT NULL,
    high        DOUBLE PRECISION  NOT NULL,
    low         DOUBLE PRECISION  NOT NULL,
    close       DOUBLE PRECISION  NOT NULL,
    volume      DOUBLE PRECISION  NOT NULL DEFAULT 0,
    spread_avg  DOUBLE PRECISION  NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, timeframe, time)
);
SELECT create_hypertable('ohlcv', 'time', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_ohlcv_tf_time ON ohlcv (symbol, timeframe, time DESC);

-- -----------------------------------------------------------------------------
-- trades — one row per trade lifecycle
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol          TEXT        NOT NULL,
    direction       TEXT        NOT NULL CHECK (direction IN ('BUY', 'SELL')),
    size            DOUBLE PRECISION NOT NULL,
    entry_price     DOUBLE PRECISION NOT NULL,
    exit_price      DOUBLE PRECISION,
    sl              DOUBLE PRECISION,
    tp              DOUBLE PRECISION,
    opened_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at       TIMESTAMPTZ,
    pnl             DOUBLE PRECISION,
    pips            DOUBLE PRECISION,
    duration_s      INTEGER,
    spk_score       DOUBLE PRECISION,
    spk_confidence  DOUBLE PRECISION,
    regime          TEXT,
    session         TEXT,
    status          TEXT        NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN', 'CLOSED', 'CANCELLED', 'REJECTED')),
    mt5_ticket      BIGINT,
    metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_trades_opened_at ON trades (opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status);

-- -----------------------------------------------------------------------------
-- agent_decisions — every agent vote per cycle (short-mid retention)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_decisions (
    time        TIMESTAMPTZ       NOT NULL DEFAULT now(),
    trade_id    UUID,
    agent_id    TEXT              NOT NULL,
    division    TEXT              NOT NULL,
    timeframe   TEXT,
    vote        SMALLINT          NOT NULL,
    confidence  DOUBLE PRECISION  NOT NULL,
    weight      DOUBLE PRECISION  NOT NULL,
    veto        TEXT,
    reasoning   TEXT,
    latency_ms  DOUBLE PRECISION,
    metadata    JSONB             NOT NULL DEFAULT '{}'::jsonb
);
SELECT create_hypertable('agent_decisions', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_agent ON agent_decisions (agent_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_trade ON agent_decisions (trade_id);

-- -----------------------------------------------------------------------------
-- trade_lessons — auto-generated post-trade analysis
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trade_lessons (
    time        TIMESTAMPTZ       NOT NULL DEFAULT now(),
    trade_id    UUID,
    regime      TEXT,
    outcome     TEXT              CHECK (outcome IN ('WIN', 'LOSS', 'BREAKEVEN')),
    root_cause  TEXT,
    action      TEXT,
    score       DOUBLE PRECISION,
    tags        TEXT[]            NOT NULL DEFAULT '{}',
    metadata    JSONB             NOT NULL DEFAULT '{}'::jsonb
);
SELECT create_hypertable('trade_lessons', 'time', chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);

-- -----------------------------------------------------------------------------
-- agent_weights — adaptive weighting state (regular table)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_weights (
    agent_id        TEXT PRIMARY KEY,
    division        TEXT        NOT NULL,
    weight          DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    default_weight  DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    trades_seen     INTEGER     NOT NULL DEFAULT 0,
    wins            INTEGER     NOT NULL DEFAULT 0,
    losses          INTEGER     NOT NULL DEFAULT 0,
    winrate         DOUBLE PRECISION,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- regimes — detected market regimes (regular table)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regimes (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT        NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at    TIMESTAMPTZ,
    features    JSONB       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_regimes_detected_at ON regimes (detected_at DESC);

-- -----------------------------------------------------------------------------
-- schema_migrations — track applied migration files
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
