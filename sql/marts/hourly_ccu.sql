-- "CCU per hour".
--
-- ASSUMPTION: "CCU per hour" means the AVERAGE of the minute-level `ccu`
-- observations within each hour (see docs/assumptions.md).

SELECT
  TIMESTAMP_TRUNC(timestamp, HOUR) AS hour,
  AVG(ccu) AS avg_ccu
FROM `analytics.detailed_ccu`
WHERE timestamp BETWEEN @start_time AND @end_time   -- optional
GROUP BY hour
ORDER BY hour;
