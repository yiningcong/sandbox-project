"""DAU calculation tests (the core business metric)."""
from __future__ import annotations

from datetime import date


def session(user_id, timestamp, duration, platform):
    return {"user_id": user_id, "timestamp": timestamp, "duration": duration, "platform": platform}


ACCOUNTS = [
    {"user_id": "user_001", "country": "DE"},
    {"user_id": "user_002", "country": "US"},
]


def test_dau_counts_unique_users_not_sessions(run_transform):
    # Test 1: user1 -> two sessions on the same day, user2 -> one session.
    # DAU must be 2, not 3.
    _, dau = run_transform(ACCOUNTS, [
        session("user_001", "2026-09-20T10:00:00", 100, "Windows"),
        session("user_001", "2026-09-20T15:00:00", 200, "Windows"),
        session("user_002", "2026-09-20T11:00:00", 300, "Android"),
    ])
    assert dau.daily == [(date(2026, 9, 20), 2)]
    assert dau.dau_total == 2


def test_multi_platform_dau_is_not_summed(run_transform):
    # Test 2: user1 -> Windows AND Android on the same day.
    # overall DAU = 1, Windows DAU = 1, Android DAU = 1.
    _, dau = run_transform(ACCOUNTS, [
        session("user_001", "2026-09-20T10:00:00", 100, "Windows"),
        session("user_001", "2026-09-20T15:00:00", 200, "Android"),
    ])
    assert dau.dau_total == 1
    assert dict(dau.by_platform) == {"Windows": 1, "Android": 1}
    assert dict(dau.by_country) == {"DE": 1}


def test_country_propagated_from_account(run_transform):
    # Test 3: the account country must reach the analytical model.
    _, dau = run_transform(ACCOUNTS, [
        session("user_002", "2026-09-20T10:00:00", 100, "iOS"),
    ])
    assert dict(dau.by_country) == {"US": 1}


def test_dau_by_date_is_per_day(warehouse, run_transform):
    # Same user on two different days counts toward each day's DAU.
    _, dau = run_transform(ACCOUNTS, [
        session("user_001", "2026-09-20T10:00:00", 100, "Windows"),
        session("user_001", "2026-09-21T10:00:00", 100, "Windows"),
    ])
    assert dau.daily == [(date(2026, 9, 20), 1), (date(2026, 9, 21), 1)]
    # Distinct users across the whole window is still 1 (not summed).
    assert dau.dau_total == 1
