-- =============================================================================
-- GoldScalper — 003 retention policies
-- Drop chunks older than the configured retention window.
-- =============================================================================

-- Raw ticks: 7 days (short-lived, high volume)
SELECT add_retention_policy('ticks', INTERVAL '7 days', if_not_exists => TRUE);

-- OHLCV: 5 years (historical backtest corpus)
SELECT add_retention_policy('ohlcv', INTERVAL '5 years', if_not_exists => TRUE);

-- Agent decisions: 1 year (audit + learning)
SELECT add_retention_policy('agent_decisions', INTERVAL '1 year', if_not_exists => TRUE);

-- Lessons: keep indefinitely (long-term learning) — intentionally no policy.
-- If retention is desired later, uncomment:
-- SELECT add_retention_policy('trade_lessons', INTERVAL '5 years', if_not_exists => TRUE);
