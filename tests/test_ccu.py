"""Part 3 — CCU per hour: aggregation logic and the documented assumption."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "marts" / "hourly_ccu.sql"


def _load_ccu(conn, rows):
    conn.execute(
        "CREATE OR REPLACE TABLE detailed_ccu AS "
        "SELECT ts, ccu FROM (VALUES "
        + ", ".join(f"('{ts}'::TIMESTAMP, {ccu})" for ts, ccu in rows)
        + ") t(ts, ccu)"
    )


def test_hourly_ccu_is_average_of_minutes(warehouse):
    # Test 5: minute-level values 10, 20, 30, 40 -> hourly average 25.
    _load_ccu(warehouse, [
        ("2026-09-20T10:00:00", 10.0),
        ("2026-09-20T10:01:00", 20.0),
        ("2026-09-20T10:02:00", 30.0),
        ("2026-09-20T10:03:00", 40.0),
    ])
    hour, avg_ccu = warehouse.execute(
        "SELECT date_trunc('hour', ts), AVG(ccu) FROM detailed_ccu GROUP BY 1"
    ).fetchone()
    assert avg_ccu == 25.0
    assert hour == datetime(2026, 9, 20, 10, 0)


def test_hours_are_bucketed_separately(warehouse):
    _load_ccu(warehouse, [
        ("2026-09-20T09:59:00", 100.0),
        ("2026-09-20T10:00:00", 200.0),
    ])
    rows = warehouse.execute(
        "SELECT date_trunc('hour', ts), AVG(ccu) FROM detailed_ccu GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert rows == [
        (datetime(2026, 9, 20, 9, 0), 100.0),
        (datetime(2026, 9, 20, 10, 0), 200.0),
    ]


def test_hourly_ccu_sql_returns_only_hour_and_average():
    # Contract check: the shipped BigQuery query returns exactly hour + AVG(ccu) —
    # no MAX / COUNT, per the assignment ("a query that returns CCU per hour").
    text = SQL_FILE.read_text()
    assert "TIMESTAMP_TRUNC(timestamp, HOUR)" in text
    assert "AVG(ccu)" in text
    assert "MAX(ccu)" not in text
    assert "COUNT(*)" not in text
