# Showing the result in Looker Studio

Looker Studio has **no way to read local files** — Parquet, DuckDB, and the local
`dashboard/index.html` are all invisible to it. It only connects to data sources it
can reach over the network. So the local dashboard I built is a *working visualization*,
not the Looker Studio report itself; to get the result **into** Looker Studio you feed
it one of the data sources below.

Both paths consume the **same two files**, produced by:

```bash
make looker-export   # writes looker_studio/fact_daily_user_activity.csv + hourly_ccu.csv
```

| File | Shape | Used for |
|---|---|---|
| `looker_studio/fact_daily_user_activity.csv` | `(activity_date, user_id, country, platform)`, 545,204 rows | DAU (all charts + filters) |
| `looker_studio/hourly_ccu.csv` | `(timestamp, avg_ccu)`, 24 rows | CCU-per-hour demo |

Why the fact table is exported **at user granularity and not pre-aggregated**: DAU is a
`COUNT(DISTINCT user_id)`, and it is non-additive across platforms (one user on Windows
*and* Android in a day is one DAU overall but appears once per platform). Only a
user-level table lets Looker Studio compute the correct distinct count *after* a country
or platform filter is applied. A pre-aggregated cube would return wrong numbers the
moment a filter is selected.

---

## Path A — Google Sheets (no cloud credentials)

This is the "runs locally" analog, in the same spirit as DuckDB standing in for
BigQuery: the only thing it needs is your Google account. The fact table is 545k rows ×
4 columns ≈ 2.2M cells, comfortably under Google Sheets' 10M-cell limit.

### 1. Upload to Google Sheets

1. Go to [sheets.google.com](https://sheets.google.com) → **Blank**.
2. **File → Import → Upload** → select `looker_studio/fact_daily_user_activity.csv` →
   *Import location*: **Replace spreadsheet** → Import data.
3. Confirm `activity_date` was detected as a **date**. If it renders as left-aligned
   text, select the whole column → **Format → Number → Date** (or *Custom date and time*
   → `2023-09-18`). Looker Studio reads the cell type, so this must be a real Date.
4. Add the CCU tab: **Insert → Sheet** (a new tab appears), then
   **File → Import → Upload** → `looker_studio/hourly_ccu.csv` → import **into that tab**.
   Format the `timestamp` column as *Date time*.

### 2. Connect Looker Studio

1. Go to [lookerstudio.google.com](https://lookerstudio.google.com) → **Create → Report**.
2. On **Add data to report**, choose **Google Sheets** → pick your spreadsheet → pick the
   `fact` tab → **Add**.
3. In the **data** panel, confirm the field types: `activity_date` → Date,
   `user_id` / `country` / `platform` → Text. If not, click the type chip and fix it.

### 3. Build the report (one data source, shared by all charts)

Add the controls first, then the charts:

| Element | Looker Studio action | Field(s) |
|---|---|---|
| Date range control | Add a control → **Date range control** | `activity_date` (default to "Last 28 days"; any multi-year range works) |
| Country filter | Add a control → **Drop-down list** | `country` |
| Platform filter | Add a control → **Drop-down list** | `platform` |
| **DAU scorecard** | Add a chart → **Scorecard** | Metric `user_id`, aggregation **Count Distinct** |
| **DAU over time** | Add a chart → **Time series** | Dimension `activity_date`, Metric `user_id` (Count Distinct) |
| **DAU by country** | Add a chart → **Bar** | Dimension `country`, Metric `user_id` (Count Distinct), sort desc |
| **DAU by platform** | Add a chart → **Bar** | Dimension `platform`, Metric `user_id` (Count Distinct), sort desc |

**The one thing that must be right:** every DAU metric is `user_id` aggregated as
**Count Distinct** (`COUNT_DISTINCT`), *never* Count or Sum. A user on two platforms in
one day contributes two fact rows; Count Distinct is what turns that into one DAU.

### 4. CCU chart (a second, tiny data source)

1. **Add data** → Google Sheets → same spreadsheet → the `hourly_ccu` tab.
2. Add a chart → **Time series** (or column): Dimension `timestamp`, Metric `avg_ccu`
   with aggregation **Avg** (it is already per-hour, so Avg avoids double-counting).

You now have a live Looker Studio report whose date range, country, and platform
controls re-filter every chart consistently — the same result the local
`dashboard/index.html` shows.

---

## Path B — BigQuery (production target)

The scale-correct destination. This needs a Google Cloud project (credentials), which is
why the prototype defaults to local mocks — but this is what "real" looks like.

1. Create a GCP project and enable the **BigQuery API**.
2. Create the dataset and table by running `sql/schemas/bigquery_schema.sql` (creates
   `analytics.fact_daily_user_activity`, partitioned by `activity_date`, clustered by
   `country, platform`).
3. Load the fact table:

   ```bash
   bq load --source_format=CSV --skip_leading_rows=1 \
     analytics.fact_daily_user_activity \
     looker_studio/fact_daily_user_activity.csv
   ```

   (or upload the CSV via the BigQuery Console → Create table → Upload).
4. Looker Studio → **Create → Data source → BigQuery** → `analytics.fact_daily_user_activity`.
   Build the same charts as Path A (same fields, same **Count Distinct** on `user_id`).
5. Optionally centralize the DAU definition by using **Custom Query** with
   `sql/marts/daily_dau.sql`, so the metric's SQL lives in the repo, not in the report.

---

## Why the local `dashboard/index.html` still exists

It is the zero-credential, share-as-a-file proof of the *analytical model and chart
design*: identical cubes, filters, and DAU semantics to the Looker Studio spec above,
but rendering in a browser with no Google account. It is the thing to hand a reviewer
who can't open Looker Studio, while this document is the thing that puts the same result
into Looker Studio.
