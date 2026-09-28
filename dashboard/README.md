# Dashboard specification

The visualization is the **interactive web dashboard** served on GitHub Pages:

- **Live:** <https://yiningcong.github.io/sandbox-project/>
- **Source:** `dashboard/template.html` (built into `index.html` by `dashboard/build_data.py`)
- **Data:** pre-aggregated from `fact_daily_user_activity` (see "Data source" below)

The assignment allows "Google Looker Studio **or similar visualization software**"; this
dashboard is the chosen alternative. It implements the same analytical model and filters, so
the production design (BigQuery → `fact_daily_user_activity`) is unchanged.

## Data source

The dashboard never queries raw sessions — it renders the analytical model
`fact_daily_user_activity` (partitioned by `activity_date`, clustered by `country`,
`platform`).

- **Local:** `dashboard/data.json`, pre-aggregated by `dashboard/build_data.py` from
  `data/processed/fact_daily_user_activity.parquet`.
- **Production:** the same table in BigQuery (`analytics.fact_daily_user_activity`); the DAU
  definition stays centralized in `sql/marts/daily_dau.sql`.

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
- A multi-year date range works because the table is date-partitioned; the dashboard renders
  per-day DAU at whatever axis granularity the range requires.
