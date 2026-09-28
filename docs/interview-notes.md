# Interview notes

## Part 1 — Business Intelligence in Games
**1. Why BI matters in Games-as-a-Service**
Games-as-a-service are event-heavy and metric-driven. Player behavior, retention, engagement and monetization can be understood through a large amount of gameplay and business data. DAU is a key engagement metric, while CCU shows intra-day concurrency and peaks, which can be relevant for capacity planning, matchmaking and live operations.

**2. What data is processed?**
A game company typically combines several types of data:

**Player / account data**
account ID
country / region
registration and account information

**Gameplay and session data**
logins and sessions
session timestamp and duration
platform
gameplay events and player activity

**Business data**
purchases and revenue
virtual economy / transactions
subscriptions or other monetization events

**Technical / operational data**
errors and crashes
latency and service health
server / infrastructure metrics

For this assignment specifically, the relevant sources are account data in PostgreSQL and session telemetry in Elasticsearch.

**3. Who uses the analysis?**
Typical stakeholders include:

**Product managers** — engagement, retention, feature adoption
**Game designers / live operations** — player behavior, events and game balance
**Marketing** — acquisition, conversion and player segments
**Finance / management** — revenue and monetization
**Engineering / operations** — concurrency, performance and system health

**4. Typical KPIs**
**Engagement**
DAU / WAU / MAU
sessions per user
session duration

**Retention**
D1 / D7 / D30 retention
churn

**Monetization**
revenue
ARPU / ARPPU
payer conversion

**Game / service health**
CCU
peak CCU
crashes / errors
latency

**5. Connection to the assignment**
These metrics come from different source systems, which motivates an analytical layer such as BigQuery where data can be combined and modeled for BI. The dashboard then needs to let stakeholders analyze DAU across time, country and platform.

## Part 2 — DAU Dashboard Design

- **Model, don't scan.** The dashboard queries `fact_daily_user_activity`, never raw
  sessions. Raw sessions would make every chart a 500M-row scan.
- **Grain = (activity_date, user_id, platform).** This makes `COUNT(DISTINCT user_id)`
  correct while still supporting platform filters. It deliberately lets a user appear on
  two platforms the same day.
- **Filters:** date range (spanning years), country, platform — map 1:1 to the partition
  and cluster keys.
- **Charts:** DAU over time (line), DAU by country (bar), DAU by platform (bar). See
  `dashboard/README.md`.

### Key correctness points to call out

1. **DAU is per-day and must not be summed.** Summing daily DAU across a month is not MAU.
2. **Overall DAU ≠ sum of platform DAU.** A user on Windows + Android in one day is one
   user, not two.
3. **Idempotency.** Re-running a window must not duplicate rows — proven by
   `tests/test_daily_activity.py::test_idempotent_rerun` (PK upsert / BigQuery MERGE).
4. **Incrementality + late data.** A reprocess window catches late events without
   reprocessing everything (see `--reprocess-window`).

## Part 3 — CCU per Hour

- Input `detailed_ccu` is minute-level `(timestamp, ccu)`.
- **Chosen definition:** "CCU per hour" = `AVG(ccu)` of the minute observations in the hour.
- **Documented alternative:** peak = `MAX(ccu)`.
- The point is to *ask which the business means* rather than silently picking one — the
  query returns both and names the default.

## Likely follow-up questions (and answers)

- **Why BigQuery instead of querying Postgres/ES?** Postgres is transactional and would
  strain under repeated analytical scans; ES is for search/retrieval, not arbitrary SQL BI.
  BigQuery fits the analytical workload and is already present. (See architecture doc.)
- **How does this handle a user whose country changes?** The grain key is
  `(date, user, platform)`; `country` is derived from `user_id`. We don't backfill history
  on country change (documented in `daily_user_activity.sql`) — a slowly-changing-dimension
  policy would decide that explicitly.
- **How would you productionize this?** Land sources into BigQuery staging (CDC or batch),
  run `sql/marts/` as scheduled SQL (dbt), swap DuckDB for BigQuery, and point the dashboard
  to the fact table. See the scale-up section of `docs/architecture.md`.
- **What did you *not* build?** No Kafka/Spark/K8s/Terraform — out of scope for an
  interview prototype and unnecessary for the design to be correct at scale.

## How to present

1. Walk the architecture diagram (2 min).
2. Show the analytical model and the DAU SQL — emphasize grain and non-summability (2 min).
3. Run `make sample-data && make run` live, then `make test` (2 min).
4. Show `sql/marts/hourly_ccu.sql` and the average-vs-peak assumption (1 min).
