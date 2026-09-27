# Data model

## Sources

### `accounts` (PostgreSQL)

| Column | Type | Notes |
|---|---|---|
| `user_id` | STRING | primary key |
| `country` | STRING | NULL => unknown, classified `'UNKNOWN'` downstream |
| `created_at` | TIMESTAMP | prototype addition (see assumptions) |
| `updated_at` | TIMESTAMP | prototype addition |

### `sessions` (Elasticsearch)

| Column | Type | Notes |
|---|---|---|
| `user_id` | STRING | assumed on the record (see assumptions) |
| `timestamp` | TIMESTAMP | UTC |
| `duration` | FLOAT64 | seconds; `>= 0` |
| `platform` | STRING | e.g. Windows / Android / iOS |

## Analytical model

### `fact_daily_user_activity` (BigQuery; DuckDB locally)

| Column | Type | Notes |
|---|---|---|
| `activity_date` | DATE | UTC; partition key |
| `user_id` | STRING | |
| `country` | STRING | denormalized from accounts; clustering key |
| `platform` | STRING | clustering key |

**Grain:** one row per unique `(activity_date, user_id, platform)`.

```
2026-09-20 | user_001 | DE | Windows
2026-09-20 | user_001 | DE | Android     <- same user, two platforms, one day (intentional)
2026-09-20 | user_002 | US | iOS
```

Because a user can appear once per platform per day, **overall DAU** is
`COUNT(DISTINCT user_id)` over this table — never a sum of platform-level DAU.

BigQuery DDL: `PARTITION BY activity_date`, `CLUSTER BY country, platform` (see
`sql/schemas/bigquery_schema.sql`).

## CCU source

### `detailed_ccu` (BigQuery)

| Column | Type | Notes |
|---|---|---|
| `timestamp` | TIMESTAMP | minute-level |
| `ccu` | FLOAT64 | concurrent users at that minute |

Read-only for us; grouped to the hour by `sql/marts/hourly_ccu.sql`.
