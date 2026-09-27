"""Core transformation: raw sessions + accounts -> fact_daily_user_activity.

Grain: one row per ``(activity_date, user_id, platform)``. A user who is active
on two platforms in one day appears twice — this is intentional, so overall DAU
can be computed with ``COUNT(DISTINCT user_id)`` without double-counting.

Each step is a SQL statement so the logic is portable to BigQuery (see
``sql/marts/daily_user_activity.sql``):

  1. Load accounts (PostgreSQL in production) into a staging table.
  2. Load raw sessions (Elasticsearch in production) into a staging table and
     classify invalid rows with data-quality checks.
  3. Join valid sessions to accounts on ``user_id`` to obtain ``country``.
  4. Derive the UTC activity date from the event timestamp.
  5. Deduplicate to the user/day/platform grain with ``SELECT DISTINCT``.
  6. Upsert into the fact table (idempotent via ``INSERT OR REPLACE`` on the PK).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Canonical list of quarantine reasons (kept in order for deterministic output).
DQ_REASONS = (
    "null_user_id",
    "null_timestamp",
    "invalid_timestamp",
    "null_platform",
    "negative_duration",
)

_LOAD_ACCOUNTS = """
CREATE OR REPLACE TABLE _accounts AS
SELECT user_id, country
FROM read_csv_auto(?, header = true,
    columns = {'user_id': 'VARCHAR', 'country': 'VARCHAR',
               'created_at': 'VARCHAR', 'updated_at': 'VARCHAR'});
"""

# Read sessions with an explicit schema so that malformed timestamps survive as
# strings and can be classified below (auto type-inference would choke on them).
_LOAD_SESSIONS_DQ = """
CREATE OR REPLACE TABLE _sessions_dq AS
SELECT
    user_id,
    "timestamp",
    duration,
    platform,
    CASE
        WHEN user_id IS NULL OR length(trim(CAST(user_id AS VARCHAR))) = 0 THEN 'null_user_id'
        WHEN "timestamp" IS NULL THEN 'null_timestamp'
        WHEN TRY_CAST("timestamp" AS TIMESTAMP) IS NULL THEN 'invalid_timestamp'
        WHEN platform IS NULL OR length(trim(platform)) = 0 THEN 'null_platform'
        WHEN duration < 0 THEN 'negative_duration'
        ELSE NULL
    END AS dq_reason
FROM read_ndjson_auto(?,
    columns = {'user_id': 'VARCHAR', 'timestamp': 'VARCHAR',
               'duration': 'DOUBLE', 'platform': 'VARCHAR'});
"""

_UPSERT_DAILY_ACTIVITY = """
INSERT OR REPLACE INTO fact_daily_user_activity (activity_date, user_id, country, platform)
SELECT DISTINCT
    CAST(date_trunc('day', CAST(s."timestamp" AS TIMESTAMP)) AS DATE) AS activity_date,
    s.user_id,
    COALESCE(a.country, 'UNKNOWN') AS country,
    s.platform
FROM _sessions_dq AS s
LEFT JOIN _accounts AS a USING (user_id)
WHERE s.dq_reason IS NULL;
"""


@dataclass
class TransformResult:
    accounts_loaded: int
    sessions_loaded: int
    sessions_valid: int
    sessions_quarantined: int
    quarantine: dict[str, int]
    fact_rows: int
    distinct_users: int


def transform(conn, accounts_raw_path: Path, sessions_raw_path: Path) -> TransformResult:
    """Run the daily-activity transformation against DuckDB-backed staging files.

    ``accounts_raw_path`` is a CSV export of the accounts table; 
    ``sessions_raw_path`` is an NDJSON of the (already windowed) session stream.
    """
    conn.execute(_LOAD_ACCOUNTS, [str(accounts_raw_path)])
    accounts_loaded = conn.execute("SELECT COUNT(*) FROM _accounts").fetchone()[0]

    conn.execute(_LOAD_SESSIONS_DQ, [str(sessions_raw_path)])
    sessions_loaded = conn.execute("SELECT COUNT(*) FROM _sessions_dq").fetchone()[0]

    conn.execute(_UPSERT_DAILY_ACTIVITY)
    fact_rows = conn.execute("SELECT COUNT(*) FROM fact_daily_user_activity").fetchone()[0]
    distinct_users = conn.execute(
        "SELECT COUNT(DISTINCT user_id) FROM fact_daily_user_activity"
    ).fetchone()[0]

    q_rows = conn.execute(
        "SELECT dq_reason, COUNT(*) FROM _sessions_dq "
        "WHERE dq_reason IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    quarantine = {reason: count for reason, count in q_rows}
    sessions_quarantined = sum(quarantine.values())

    return TransformResult(
        accounts_loaded=accounts_loaded,
        sessions_loaded=sessions_loaded,
        sessions_valid=sessions_loaded - sessions_quarantined,
        sessions_quarantined=sessions_quarantined,
        quarantine=quarantine,
        fact_rows=fact_rows,
        distinct_users=distinct_users,
    )


@dataclass
class DAUResult:
    dau_total: int            # distinct users across the whole fact table (NOT a sum of DAU)
    avg_daily_dau: float
    daily: list[tuple]        # [(activity_date, dau), ...]
    by_country: list[tuple]   # [(country, dau), ...] desc
    by_platform: list[tuple]  # [(platform, dau), ...] desc


def query_dau(conn) -> DAUResult:
    """DAU = number of unique users active on a calendar day."""
    dau_total = conn.execute(
        "SELECT COUNT(DISTINCT user_id) FROM fact_daily_user_activity"
    ).fetchone()[0]
    daily = conn.execute(
        "SELECT activity_date, COUNT(DISTINCT user_id) AS dau "
        "FROM fact_daily_user_activity GROUP BY 1 ORDER BY 1"
    ).fetchall()
    by_country = conn.execute(
        "SELECT country, COUNT(DISTINCT user_id) AS dau "
        "FROM fact_daily_user_activity GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    by_platform = conn.execute(
        "SELECT platform, COUNT(DISTINCT user_id) AS dau "
        "FROM fact_daily_user_activity GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    avg_daily_dau = sum(d for _, d in daily) / len(daily) if daily else 0.0
    return DAUResult(dau_total, avg_daily_dau, daily, by_country, by_platform)
