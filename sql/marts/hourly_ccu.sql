-- "CCU per hour".
--
-- ASSUMPTION: "CCU per hour" means the AVERAGE of the minute-level `ccu`
-- observations within each hour. This is the default below (`avg_ccu`).
--
-- If the business definition is instead PEAK hourly concurrency, use
-- `peak_ccu` (MAX) as the metric instead. Do not mix the two definitions; pick
-- one and document it (see docs/assumptions.md).

SELECT
  TIMESTAMP_TRUNC(timestamp, HOUR) AS hour,
  AVG(ccu) AS avg_ccu,          -- default metric (mean of minute-level CCU)
  MAX(ccu) AS peak_ccu,         -- alternative metric (peak of minute-level CCU)
  COUNT(*) AS minute_samples     -- diagnostic: expected 60 per hour unless gaps
FROM `analytics.detailed_ccu`
WHERE timestamp BETWEEN @start_time AND @end_time   -- optional
GROUP BY hour
ORDER BY hour;

-- Note for the local prototype (DuckDB): DuckDB spells the same truncation as
-- `date_trunc('hour', timestamp)` rather than `TIMESTAMP_TRUNC(timestamp, HOUR)`;
-- the aggregation is identical.
