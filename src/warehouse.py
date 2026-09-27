"""Local stand-in for BigQuery, backed by DuckDB.

DuckDB is an embedded, columnar, SQL-first analytical engine — a reasonable
local analog of BigQuery for a prototype that must run without cloud
credentials. The same transformation SQL (see ``sql/marts/``) runs in BigQuery
in production; the only differences are minor function-name mappings documented
in each SQL file.

The fact table carries a PRIMARY KEY on ``(activity_date, user_id, platform)``
so ``INSERT OR REPLACE`` makes the load idempotent. BigQuery does not enforce
primary keys, so the production equivalent (``sql/marts/daily_user_activity.sql``)
uses a MERGE on the same grain instead.
"""
from __future__ import annotations

from pathlib import Path

FACT_DDL = """
CREATE TABLE IF NOT EXISTS fact_daily_user_activity (
    activity_date DATE    NOT NULL,
    user_id       VARCHAR NOT NULL,
    country       VARCHAR NOT NULL,
    platform      VARCHAR NOT NULL,
    PRIMARY KEY (activity_date, user_id, platform)
);
"""


def open_warehouse(path: str | Path | None = None):
    """Open a DuckDB connection (in-memory by default, or a file for persistence)."""
    import duckdb

    conn = duckdb.connect(str(path) if path else ":memory:")
    # Explicit UTC — the prototype never relies on the machine's local timezone.
    conn.execute("SET TimeZone = 'UTC'")
    return conn


def create_schema(conn) -> None:
    conn.execute(FACT_DDL)
