-- DAU = number of unique users active during a given calendar day.
--
-- The dashboard queries the analytical model (fact_daily_user_activity), never
-- raw sessions. Filters map to the @-parameters supplied by the BI tool.

-- ---------------------------------------------------------------------------
-- 1. DAU over time (the dashboard's main chart)
-- ---------------------------------------------------------------------------
SELECT
  activity_date,
  COUNT(DISTINCT user_id) AS dau
FROM `analytics.fact_daily_user_activity`
WHERE activity_date BETWEEN @start_date AND @end_date
  -- AND country  = @country    -- optional filter
  -- AND platform = @platform   -- optional filter
GROUP BY activity_date
ORDER BY activity_date;

-- ---------------------------------------------------------------------------
-- 2. DAU by country
-- ---------------------------------------------------------------------------
SELECT
  country,
  COUNT(DISTINCT user_id) AS dau
FROM `analytics.fact_daily_user_activity`
WHERE activity_date BETWEEN @start_date AND @end_date
GROUP BY country
ORDER BY dau DESC;

-- ---------------------------------------------------------------------------
-- 3. DAU by platform
-- ---------------------------------------------------------------------------
SELECT
  platform,
  COUNT(DISTINCT user_id) AS dau
FROM `analytics.fact_daily_user_activity`
WHERE activity_date BETWEEN @start_date AND @end_date
GROUP BY platform
ORDER BY dau DESC;

-- ---------------------------------------------------------------------------
-- IMPORTANT: a user active on multiple platforms in one day is counted ONCE in
-- overall DAU. Do NOT derive overall DAU by summing platform-level DAU — that
-- would double-count such users.
-- ---------------------------------------------------------------------------
