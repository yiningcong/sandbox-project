-- Staging view: clean, typed sessions with a UTC activity date.
--
-- In a dbt project this would be a model built on the landed `sessions` source;
-- here it is a plain view so the marts below stay readable.
--
-- Data-quality predicates mirror the quarantine logic in the prototype
-- (src/transformation/daily_activity.py): invalid rows are excluded here rather
-- than quarantined, because in production the raw layer would route them to a
-- quarantine table (see docs/assumptions.md).

CREATE OR REPLACE VIEW `analytics.stg_sessions` AS
SELECT
  user_id,
  timestamp,
  duration,
  platform,
  DATE(timestamp) AS activity_date   -- UTC date (see docs/assumptions.md)
FROM `analytics.sessions`
WHERE user_id IS NOT NULL
  AND timestamp IS NOT NULL
  AND platform IS NOT NULL
  AND duration >= 0;
