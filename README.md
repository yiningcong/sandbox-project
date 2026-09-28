# DAU ETL — Data Engineer Interview Prototype

A small, runnable prototype for the three-part interview assignment:

| Part | Deliverable | Where |
|---|---|---|
| 1 — Business Intelligence in Games | Talking points / presentation notes | `docs/interview-notes.md` |
| 2 — DAU Dashboard Design | Working pipeline + analytical model + dashboard spec | `src/`, `sql/`, `dashboard/README.md` |
| 3 — CCU per Hour SQL | Query + documented assumption | `sql/marts/hourly_ccu.sql`, `tests/test_ccu.py` |

The prototype computes **Daily Active Users** from account data (PostgreSQL) joined to
game-session events (Elasticsearch), lands a clean analytical table designed for
**BigQuery**, and exposes it for **Looker Studio**. It runs **entirely locally** — no
cloud credentials, no Docker, no daemons required.

---

## Architecture

```
PostgreSQL (accounts)  ──┐
                         ├──> extract ──> transform (join, UTC date, dedupe) ──> BigQuery
Elasticsearch (sessions) ─┘                                                         │
                                                                                    v
                                                                fact_daily_user_activity
                                                                                    │
                                                                  DAU / CCU queries ─> Looker Studio
```

Because this must run without external services, each production component has a **local
mock** that is a faithful, small-scale analog:

| Production | Local mock (default) |
|---|---|
| PostgreSQL `accounts` | CSV export of the table (`src/ingestion/postgres.py`) |
| Elasticsearch `sessions` | NDJSON files, ES bulk `_source` format (`src/ingestion/elasticsearch.py`) |
| BigQuery | **DuckDB** — embedded, columnar, SQL-first (`src/warehouse.py`) |

Set `POSTGRES_HOST` / `ELASTICSEARCH_URL` to swap the mocks for the real services
(`docker-compose.yml` starts them). The transformation SQL is written once and shipped
twice: a DuckDB version in `src/transformation/` and a BigQuery version in `sql/`.

See `docs/architecture.md` for the full picture and scale-up discussion.

---

## Assumptions

All assumptions are documented in `docs/assumptions.md`. The three that matter most:

1. **Sessions carry a stable `user_id`.** The assignment does not state this, but DAU
   requires identifying unique users, so it is assumed and stated explicitly.
2. **Timestamps are UTC.** Activity date is derived in UTC (the code never touches the
   machine's local timezone).
3. **"CCU per hour" = average of minute-level `ccu`.** The alternative (peak = `MAX`) is
   documented alongside it; the definition is a business choice, not hidden.

---

## Quick start

Requires **Python 3.11+** and, on macOS, Homebrew `pyenv` (used to install the exact
pinned version — see "Setup" below).

```bash
make setup          # one-time: installs Python 3.11.8 via pyenv, creates .venv, installs deps
make sample-data    # generate the deterministic sample dataset into data/sample/
make run            # run the full DAU pipeline on the sample data
make ccu            # run the hourly-CCU demo query
make test           # run the pytest suite
```

You don't need Docker. `make clean` removes generated data.

### Setup (details)

`make setup` installs the exact interpreter in `PYTHON_VERSION` (default `3.11.8`) through
**pyenv**, then creates `.venv` and installs dependencies from `pyproject.toml`. brew is not
used here because `python@3.11` can't pin a specific patch version. To use your own
interpreter instead:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Optional real-service adapters need extra deps: `.venv/bin/pip install -e ".[docker]"`.

### Run against real PostgreSQL + Elasticsearch

The prototype runs on local files by default; the same pipeline can read the real services
instead. Start them, seed them from the deterministic sample, then run:

```bash
docker compose up -d                              # postgres:16 + elasticsearch:8.13.4
make docker-setup                                 # installs psycopg + elasticsearch (<9)
export POSTGRES_HOST=localhost ELASTICSEARCH_URL=http://localhost:9200
export POSTGRES_USER=etl POSTGRES_PASSWORD=etl POSTGRES_DB=accounts   # match docker-compose
make seed                                         # load accounts -> PG, sessions -> ES
make run                                          # extract from PG + ES, not local files
```

`src/seed.py` creates the `accounts` table and bulk-indexes the `sessions` index (idempotent:
truncate + reload / re-create + re-index). The 200 intentionally-invalid sample records are
**not** seeded to Elasticsearch — a real typed `date` index can't hold them, so the DQ layer
reports 0 quarantined rows when reading ES (the CSV mock keeps them to exercise the DQ
checks). The pipeline output is otherwise identical between the two sources.

### See the result in Looker Studio

Looker Studio cannot read local files (Parquet / DuckDB / the local HTML dashboard) — it
only connects to sources it can reach. `make looker-export` writes the two CSVs it needs,
and `docs/looker-studio.md` walks through both ways in, click by click:

```bash
make looker-export      # looker_studio/fact_daily_user_activity.csv + hourly_ccu.csv
```

1. **Google Sheets (no cloud credentials)** — upload those two CSVs to a sheet, connect
   Looker Studio's Google Sheets connector, and add `COUNT_DISTINCT(user_id)` metrics. This
   is the "runs locally" analog, in the same spirit as DuckDB standing in for BigQuery.
2. **BigQuery (production)** — create the table with `sql/schemas/bigquery_schema.sql`,
   load the fact CSV, and use the native connector. Scale-correct, needs GCP credentials.

The local `dashboard/index.html` is the zero-credential proof of the same model and charts.

---

## How the pipeline works

`src/pipeline.py` orchestrates the steps the assignment specifies:

1. **Extract** accounts (Postgres/CSV) and sessions (ES/NDJSON) — the sessions source
   applies a **time-range filter** so only the requested window (plus the reprocess window)
   is pulled, never the full 500M rows.
2. **Data-quality checks** — null `user_id`/`timestamp`/`platform`, invalid timestamps, and
   negative durations are **quarantined** and counted, never silently dropped.
3. **Transform** (SQL) — join `sessions → accounts` on `user_id` to get `country`, derive
   the UTC `activity_date`, and `SELECT DISTINCT` to the grain
   `(activity_date, user_id, platform)`.
4. **Load** — idempotent upsert (`INSERT OR REPLACE` on the grain's primary key locally;
   `MERGE` in BigQuery), so re-running the same window never duplicates rows.
5. **Query DAU** — `COUNT(DISTINCT user_id)`, written to `data/processed/`.

A run with the default settings produces (reproducible, seed `42`, ~3 years of data):

```
Accounts extracted         : 10,000
Sessions extracted         : 569,155  (568,955 valid, 200 quarantined)
Fact rows (date/user/platform): 545,204
Distinct users in range    : 10,001
Average daily DAU          : 437.3
```

### Incremental & late-arriving data

The pipeline is **incremental**, not "reprocess everything":

```bash
.venv/bin/python -m src.pipeline run --start-date 2026-09-22 --end-date 2026-09-23 --reprocess-window 7
```

`--reprocess-window N` re-pulls the previous `N` days (default 7) to catch late-arriving
events. It is configurable, not hardcoded — the exact value should be set from observed
source-system lateness (see `docs/assumptions.md`). Verified: with `--reprocess-window 0`,
398 fewer late sessions are extracted than with the default of 7.

### Idempotency

The grain `(activity_date, user_id, platform)` is unique by construction, and the load is
an upsert. `tests/test_daily_activity.py::test_idempotent_rerun` proves that processing the
same input twice does not create duplicate rows.

---

## How DAU is calculated

> DAU = number of **unique users** active during a calendar day.

```sql
SELECT activity_date, COUNT(DISTINCT user_id) AS dau
FROM fact_daily_user_activity
WHERE activity_date BETWEEN @start_date AND @end_date
  -- AND country  = @country
  -- AND platform = @platform
GROUP BY activity_date ORDER BY activity_date;
```

A user active on **two platforms in one day** produces two fact rows (intentionally), so
`COUNT(DISTINCT user_id)` still counts them once. **DAU for "all platforms" must never be
computed by summing platform-level DAU** — see `sql/marts/daily_dau.sql`.

## How CCU per hour is calculated

`sql/marts/hourly_ccu.sql` groups `detailed_ccu` (minute-level) to the hour and takes
`AVG(ccu)` (the documented default); `MAX(ccu)` is provided as the "peak" alternative. The
local demo (`make ccu`) runs the equivalent DuckDB query against
`data/sample/detailed_ccu.csv`.

---

## Repository layout

```
├── Makefile                 # setup / sample-data / run / ccu / dashboard / looker-export / seed / test / clean
├── pyproject.toml           # deps: duckdb (+ optional psycopg/elasticsearch)
├── docker-compose.yml       # optional real Postgres + Elasticsearch
├── docs/                    # architecture, assumptions, data model, interview notes, looker-studio
├── src/
│   ├── ingestion/           # Postgres + Elasticsearch sources (mock + real)
│   ├── transformation/      # daily_activity transform (SQL) + DAU query
│   ├── warehouse.py         # DuckDB = local BigQuery
│   ├── sample_data.py       # deterministic sample generator
│   └── pipeline.py          # orchestration + CLI
├── sql/
│   ├── staging/             # stg_sessions.sql
│   ├── marts/               # daily_user_activity.sql, daily_dau.sql, hourly_ccu.sql
│   └── schemas/             # bigquery_schema.sql (partitioned + clustered)
├── dashboard/               # local HTML dashboard + looker_studio CSV export
├── tests/                   # pytest (DAU, dedupe, DQ, CCU, reproducibility)
├── dashboard/README.md      # Looker Studio connection + dashboard spec
├── looker_studio/           # CSVs to upload to Google Sheets / BigQuery (generated)
└── data/                    # raw/ processed/ sample/ (generated)
```

---

## Scaling to 30M accounts / 500M sessions

The design is scale-invariant; only the engines change:

- **Extraction** already filters by time at the source (ES range query / Postgres
  server-side cursor), so a daily job pulls a window, not the full history.
- **Transformation** is pure SQL — in production it runs *inside BigQuery* (`sql/marts/`),
  which is built for exactly this scale; the local DuckDB flow is the same query at toy
  scale.
- **The fact table** is partitioned by `activity_date` and clustered by `country, platform`
  to match the dashboard's dominant filters (date range, country, platform), and the MERGE
  upsert is idempotent at scale.
- **Late arrivals** are handled by a bounded reprocess window rather than full restates.

See `docs/architecture.md` for the trade-offs (why BigQuery vs. querying Postgres/ES
directly) and `docs/interview-notes.md` for likely follow-up questions.
