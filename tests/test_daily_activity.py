"""Transformation tests: deduplication, idempotency, DQ / missing data."""
from __future__ import annotations


def session(user_id, timestamp, duration, platform):
    return {"user_id": user_id, "timestamp": timestamp, "duration": duration, "platform": platform}


ACCOUNTS = [
    {"user_id": "user_001", "country": "DE"},
    {"user_id": "user_002", "country": "US"},
]


def test_duplicate_sessions_do_not_duplicate_fact_rows(run_transform):
    # Test 4: the same source session twice -> exactly one fact row.
    s = session("user_001", "2026-09-20T10:00:00", 100, "Windows")
    tresult, _ = run_transform(ACCOUNTS, [s, s])
    assert tresult.fact_rows == 1


def test_grain_is_unique_user_day_platform(warehouse, run_transform):
    run_transform(ACCOUNTS, [
        session("user_001", "2026-09-20T10:00:00", 100, "Windows"),
        session("user_001", "2026-09-20T11:00:00", 100, "Android"),
        session("user_001", "2026-09-21T10:00:00", 100, "Windows"),
    ])
    total = warehouse.execute("SELECT COUNT(*) FROM fact_daily_user_activity").fetchone()[0]
    distinct_grain = warehouse.execute(
        "SELECT COUNT(DISTINCT (activity_date, user_id, platform)) FROM fact_daily_user_activity"
    ).fetchone()[0]
    assert total == distinct_grain == 3


def test_idempotent_rerun(warehouse, make_sources):
    # Running the same input twice must not create duplicate daily activity rows.
    acc, sess = make_sources(ACCOUNTS, [
        session("user_001", "2026-09-20T10:00:00", 100, "Windows"),
        session("user_001", "2026-09-20T15:00:00", 200, "Windows"),
        session("user_002", "2026-09-20T11:00:00", 300, "Android"),
    ])
    from src.transformation.daily_activity import transform

    transform(warehouse, acc, sess)
    first = warehouse.execute("SELECT COUNT(*) FROM fact_daily_user_activity").fetchone()[0]
    transform(warehouse, acc, sess)
    second = warehouse.execute("SELECT COUNT(*) FROM fact_daily_user_activity").fetchone()[0]
    assert first == second == 2


def test_unknown_country_classified(run_transform):
    # A session whose user has no account -> country 'UNKNOWN', not dropped.
    tresult, dau = run_transform([], [
        session("user_999", "2026-09-20T10:00:00", 100, "Windows"),
    ])
    assert tresult.fact_rows == 1
    assert dict(dau.by_country) == {"UNKNOWN": 1}


def test_invalid_rows_are_quarantined(run_transform):
    # Test 6: null/invalid fields and negative durations must not reach the fact table.
    tresult, dau = run_transform(ACCOUNTS, [
        {"user_id": None, "timestamp": "2026-09-20T10:00:00", "duration": 100, "platform": "Windows"},    # null_user_id
        {"user_id": "user_001", "timestamp": None, "duration": 100, "platform": "Windows"},                  # null_timestamp
        {"user_id": "user_001", "timestamp": "not-a-date", "duration": 100, "platform": "Windows"},          # invalid_timestamp
        {"user_id": "user_001", "timestamp": "2026-09-20T10:00:00", "duration": 100, "platform": None},      # null_platform
        {"user_id": "user_001", "timestamp": "2026-09-20T10:00:00", "duration": -5, "platform": "Windows"}, # negative_duration
        session("user_002", "2026-09-20T12:00:00", 100, "iOS"),                                              # valid
    ])
    assert tresult.sessions_loaded == 6
    assert tresult.sessions_valid == 1
    assert tresult.sessions_quarantined == 5
    assert tresult.quarantine == {
        "null_user_id": 1,
        "null_timestamp": 1,
        "invalid_timestamp": 1,
        "null_platform": 1,
        "negative_duration": 1,
    }
    assert tresult.fact_rows == 1
    assert dau.dau_total == 1


def test_empty_user_id_and_platform_treated_as_null(run_transform):
    tresult, _ = run_transform(ACCOUNTS, [
        {"user_id": "", "timestamp": "2026-09-20T10:00:00", "duration": 100, "platform": "Windows"},
        {"user_id": "user_001", "timestamp": "2026-09-20T10:00:00", "duration": 100, "platform": "  "},
    ])
    assert tresult.sessions_quarantined == 2
    assert tresult.quarantine == {"null_user_id": 1, "null_platform": 1}
