# Interview notes

## Part 1 — Business Intelligence in Games

1. **Why BI matters in Games-as-a-Service**

  Games-as-a-service are event-heavy and metric-driven. Player behavior, retention,
  engagement and monetization can be understood through a large amount of gameplay
  and business data. DAU is a key engagement metric, while CCU shows intra-day
  concurrency and peaks — relevant for capacity planning, matchmaking and live
  operations.

2. **What data is processed**

  A game company typically combines several types of data:

  - **Player / account data** — account ID, country / region, registration and account
    information
  - **Gameplay / session data** — logins and sessions, session timestamp and duration,
    platform, gameplay events and player activity
  - **Business data** — purchases and revenue, virtual economy / transactions,
    subscriptions or other monetization events
  - **Technical / operational data** — errors and crashes, latency and service health,
    server / infrastructure metrics

  For this assignment, the relevant sources are account data in PostgreSQL and session
  telemetry in Elasticsearch.

3. **Who uses the analysis**

  - **Product managers** — engagement, retention, feature adoption
  - **Game designers / live operations** — player behavior, events and game balance
  - **Marketing** — acquisition, conversion and player segments
  - **Finance / management** — revenue and monetization
  - **Engineering / operations** — concurrency, performance and system health

4. **Typical KPIs**

  - **Engagement** — DAU / WAU / MAU, sessions per user, session duration
  - **Retention** — D1 / D7 / D30 retention, churn
  - **Monetization** — revenue, ARPU / ARPPU, payer conversion
  - **Game / service health** — CCU, peak CCU, crashes / errors, latency

5. **Connection to the assignment**

  These metrics come from different source systems, which motivates an analytical layer
  such as BigQuery where data can be combined and modeled for BI. The dashboard then
  needs to let stakeholders analyze DAU across time, country and platform.

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
- **Definition:** "CCU per hour" = `AVG(ccu)` of the minute observations in the hour — the
  query returns just `(hour, AVG(ccu))`, as the assignment asks.
- The corresponding SQL query is in `sql/marts/hourly_ccu.sql`.
- If the business definition is instead **peak CCU per hour**, use `MAX(ccu)`.
