# Assumptions

The assignment deliberately leaves some details unspecified. Where information was missing,
the assumption is documented here rather than silently invented. Every assumption is
traceable to a line of code or a SQL file.

## 1. Sessions carry a stable user identifier

> **Assumption:** each session can be associated with a stable user/account identifier.

The assignment says sessions contain `timestamp`, `duration` and `platform` but does not say
they contain `user_id`. DAU *requires* identifying unique users, so `user_id` is assumed to
exist on the session record. This is not hidden — it is the join key in
`sql/marts/daily_user_activity.sql` (`sessions.user_id = accounts.user_id`).

## 2. Timestamps are UTC

> **Assumption:** source timestamps are UTC; activity date is derived in UTC unless the
> business specifies a different reporting timezone.

`src/warehouse.py` sets `SET TimeZone = 'UTC'`, and the activity date is
`DATE(timestamp)` / `date_trunc('day', …)` with no local-timezone conversion. The machine's
local timezone is never consulted.

## 3. "CCU per hour" means the average of minute-level CCU

> **Assumption:** "CCU per hour" = `AVG(ccu)` over the minute-level observations in that hour.

`sql/marts/hourly_ccu.sql` implements `AVG(ccu)` as the default metric and also returns
`MAX(ccu)` for reference. If the business means *peak* hourly concurrency, use `MAX` — but
the definition must be chosen once and documented, not mixed. (See Part 3 in the notes.)

## 4. Country comes from accounts; unknown is classified

`country` lives on the account and is obtained by joining `sessions.user_id → accounts.user_id`.
It is **not** duplicated into the raw session source. A session whose user has no account
gets `country = 'UNKNOWN'` (classified, not dropped). Denormalizing `country` into the fact
table is an analytical optimization, not a new source of truth.

## 5. `created_at` / `updated_at` are prototype additions

Not specified by the assignment. They are added to `accounts` to demonstrate incremental
ingestion and are clearly marked as such in `sql/schemas/bigquery_schema.sql`.

## 6. The lateness window is configurable, not fixed

The pipeline reprocesses a configurable window (`REPROCESS_WINDOW_DAYS`, default 7) before
the start date to catch late-arriving events.

> **Assumption:** the exact lateness window should be based on observed source-system
> behavior; 7 is a placeholder default, not a product decision.

## 7. Window bounds are inclusive start / exclusive end

The extraction window is `[start_date, end_date)` in event time (UTC). This is the
convention used consistently across the source adapters and the SQL.

## 8. Invalid data is quarantined, not silently dropped or "fixed"

The prototype applies only the checks the assignment lists — it does not invent business
rules for invalid rows:

| Check | Action |
|---|---|
| `user_id` null/empty | quarantine |
| `timestamp` null | quarantine |
| `timestamp` unparseable | quarantine |
| `platform` null/empty | quarantine |
| `duration < 0` | quarantine |
| `country` missing after join | classify `'UNKNOWN'` |

Quarantined rows are counted in `data/processed/dq_report.json`. In production these would
be routed to a quarantine table and alerted on; the prototype counts them because the
assignment does not specify what to do with them beyond not corrupting the fact table.

## 9. No unmeasured performance claims

Partitioning by `activity_date` and clustering by `country, platform` are recommended
because the dashboard filters on those dimensions. The docs state *why* (date filtering is
common, country/platform filtering is required, partitioning prunes scans) but make no
specific latency/throughput claims — none were measured.
