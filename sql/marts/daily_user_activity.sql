-- fact_daily_user_activity: one row per (activity_date, user_id, platform).
--
-- Steps: join sessions -> accounts on user_id to obtain country, derive the UTC
-- activity date, deduplicate with SELECT DISTINCT, and upsert via MERGE so
-- re-running the same window never duplicates rows (idempotent).
--
-- The local DuckDB prototype uses `INSERT OR REPLACE` on an equivalent PRIMARY
-- KEY instead, because DuckDB supports PKs and BigQuery does not.
--
-- A user active on two platforms in one day legitimately produces two rows; the
-- downstream DAU query uses COUNT(DISTINCT user_id), so that user is counted once.

MERGE `analytics.fact_daily_user_activity` AS t
USING (
  SELECT DISTINCT
    s.activity_date,
    s.user_id,
    COALESCE(a.country, 'UNKNOWN') AS country,
    s.platform
  FROM `analytics.stg_sessions` AS s
  LEFT JOIN `analytics.accounts` AS a USING (user_id)
  WHERE s.activity_date BETWEEN @start_date AND @end_date
) AS s
ON t.activity_date = s.activity_date
   AND t.user_id = s.user_id
   AND t.platform = s.platform
WHEN NOT MATCHED THEN
  INSERT (activity_date, user_id, country, platform)
  VALUES (s.activity_date, s.user_id, s.country, s.platform);

-- NOTE: We do not add `WHEN MATCHED THEN UPDATE` because the grain key
-- (date, user, platform) determines the row; `country` is a function of user_id
-- and is constant for a given grain. If a user's country can change
-- retroactively, decide explicitly whether to backfill history (slowly-changing
-- dimension policy) before enabling an UPDATE clause.
