-- BigQuery analytical schema (production).
-- The local DuckDB equivalent lives in src/warehouse.py.
--
-- NOTE: `accounts` and `sessions` are source-system tables (PostgreSQL and
-- Elasticsearch respectively). In production they are *landed* into BigQuery by
-- the ingestion layer (e.g. a CDC/streaming connector or a batch COPY) so the
-- transformation below can run entirely in SQL. The prototype reads its local
-- CSV/NDJSON stand-ins instead.

-- ---------------------------------------------------------------------------
-- Source: accounts (from PostgreSQL)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `analytics.accounts` (
  user_id    STRING    NOT NULL,
  country    STRING,               -- NULL => unknown; classified 'UNKNOWN' downstream
  created_at TIMESTAMP,            -- prototype addition (not in the assignment)
  updated_at TIMESTAMP             -- prototype addition (for incremental ingestion)
);

-- ---------------------------------------------------------------------------
-- Source: sessions (from Elasticsearch)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `analytics.sessions` (
  user_id   STRING    NOT NULL,
  timestamp TIMESTAMP NOT NULL,    -- UTC (see docs/assumptions.md)
  duration  FLOAT64,
  platform  STRING    NOT NULL
)
-- If sessions are landed incrementally, partition by event date:
-- PARTITION BY DATE(timestamp)
-- CLUSTER BY user_id
;

-- ---------------------------------------------------------------------------
-- Analytical model: fact_daily_user_activity
--
-- Grain: one row per (activity_date, user_id, platform).
-- Partition by date (the dominant dashboard filter) and cluster by the two
-- remaining required filters (country, platform).
--
-- BigQuery does not enforce primary keys, so idempotency is achieved with the
-- MERGE in sql/marts/daily_user_activity.sql on the same (date, user, platform)
-- grain.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `analytics.fact_daily_user_activity` (
  activity_date DATE    NOT NULL,
  user_id       STRING  NOT NULL,
  country       STRING  NOT NULL,
  platform      STRING  NOT NULL
)
PARTITION BY activity_date
CLUSTER BY country, platform;

-- ---------------------------------------------------------------------------
-- CCU source (assumed to already exist; minute-level). Read-only for us.
-- ---------------------------------------------------------------------------
-- CREATE TABLE `analytics.detailed_ccu` (
--   timestamp TIMESTAMP NOT NULL,
--   ccu       FLOAT64   NOT NULL
-- )
-- PARTITION BY DATE(timestamp);
