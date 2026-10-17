-- =============================================================================
-- GoldScalper — 002 compression policies
-- Compress older chunks to reduce storage & speed historical scans.
-- =============================================================================

ALTER TABLE ticks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('ticks', INTERVAL '2 days', if_not_exists => TRUE);

ALTER TABLE ohlcv SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, timeframe',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('ohlcv', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE agent_decisions SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'agent_id',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('agent_decisions', INTERVAL '7 days', if_not_exists => TRUE);

ALTER TABLE trade_lessons SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'regime',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('trade_lessons', INTERVAL '90 days', if_not_exists => TRUE);
