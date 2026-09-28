# Dashboard specification (Looker Studio)

> **To actually see this in Looker Studio**, run `make looker-export` and follow
> `docs/looker-studio.md` — it walks through the Google Sheets connector (no cloud
> credentials) and the production BigQuery path. Looker Studio cannot read the local
> Parquet/HTML directly; that is why this file is a spec rather than a live report.

The dashboard queries the **analytical model** (`fact_daily_user_activity` in BigQuery),
never raw sessions. Looker Studio connects to BigQuery with the native connector.

## Data source

- **Connector:** BigQuery (native in Looker Studio).
- **Table:** `analytics.fact_daily_user_activity` (partitioned by `activity_date`,
  clustered by `country`, `platform`).
- **Custom SQL (optional):** use the queries in `sql/marts/daily_dau.sql` so the DAU
  definition is centralized.

## Filters

| Filter | Field | Type | Notes |
|---|---|---|---|
| Date range | `activity_date` | date range | spans multiple years; partitioned → prunes old dates |
| Country | `country` | drop-down | sourced from `DISTINCT country` |
| Platform | `platform` | drop-down | Windows / Android / iOS |

## Metrics

| Metric | Definition |
|---|---|
| **DAU** | `COUNT(DISTINCT user_id)` |
| Average DAU (range) | `AVG` of daily DAU, not a sum |

## Charts

1. **DAU over time** — time-series line of `COUNT(DISTINCT user_id)` grouped by
   `activity_date`.
2. **DAU by country** — bar chart of `COUNT(DISTINCT user_id)` grouped by `country`.
3. **DAU by platform** — bar chart of `COUNT(DISTINCT user_id)` grouped by `platform`.

All three share the same filters, so selecting a country re-filters every chart
consistently.

## Correctness notes

- A user on **multiple platforms in one day** is one DAU overall but appears once per
  platform in the "DAU by platform" chart. Do **not** configure the overall DAU scorecard
  as a sum of the platform bars — it would double-count those users.
- A multi-year date range works because the table is date-partitioned; the query still
  returns per-day DAU, and Looker Studio handles the axis granularity.
