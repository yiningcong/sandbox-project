"""Deterministic sample-data generator.

Produces a reproducible local dataset in ``data/sample/``:

  * ``accounts.csv``    — 10,000 accounts (user_id, country, created_at, updated_at)
  * ``sessions.ndjson`` — sessions (user_id, timestamp, duration, platform) spanning
    ~3 years, including exact duplicates, same-day multi-platform activity,
    late-arriving events, and a small number of intentionally invalid records used
    to exercise the data-quality checks.
  * ``detailed_ccu.csv`` — one day of minute-level CCU (for the hourly CCU query)

A fixed RNG seed guarantees the exact same dataset on every run. The multi-year span
exists so the dashboard's date-range selector can exercise year-length windows.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
import random

from src.config import DEFAULT_END_DATE, PROJECT_ROOT

SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"

COUNTRIES = ["US", "DE", "GB", "JP", "BR", "FR", "KR", "IN", "CA", "AU"]
COUNTRY_WEIGHTS = [0.30, 0.15, 0.10, 0.10, 0.08, 0.07, 0.07, 0.05, 0.04, 0.04]

PLATFORMS = ["Windows", "Android", "iOS"]
PLATFORM_WEIGHTS = [0.45, 0.35, 0.20]

# Average sessions-per-hour curve for a games company (UTC). Peaks in the evening.
HOUR_WEIGHTS = [
    8, 5, 4, 3, 3, 4, 6, 9, 12, 14, 15, 16, 17, 18, 19, 21, 22, 23,
    25, 27, 28, 27, 24, 18,
]

_TS = "%Y-%m-%dT%H:%M:%S"


def _weighted_choice(rng: random.Random, values: list, weights: list):
    return rng.choices(values, weights=weights, k=1)[0]


def _ts(dt: datetime) -> str:
    return dt.strftime(_TS)


def generate(
    accounts: int = 10_000,
    sessions: int = 500_000,
    days: int = 1095,
    end_date: str = DEFAULT_END_DATE,
    seed: int = 42,
    out_dir: Path = SAMPLE_DIR,
) -> dict[str, Path]:
    """Generate the sample dataset and return a mapping of name -> path."""
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    end = datetime.fromisoformat(end_date)
    start_day = end - timedelta(days=days - 1)

    # --- Accounts -----------------------------------------------------------
    accounts_path = out_dir / "accounts.csv"
    with accounts_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["user_id", "country", "created_at", "updated_at"])
        for i in range(accounts):
            user_id = f"user_{i:06d}"
            country = _weighted_choice(rng, COUNTRIES, COUNTRY_WEIGHTS)
            created = end - timedelta(days=rng.randint(200, 400), seconds=rng.randint(0, 86_400))
            updated = created + timedelta(days=rng.randint(0, 30), seconds=rng.randint(0, 86_400))
            writer.writerow([user_id, country, _ts(created), _ts(updated)])

    # --- Sessions -----------------------------------------------------------
    sessions_path = out_dir / "sessions.ndjson"
    n_accounts = accounts
    with sessions_path.open("w") as fh:
        def emit(user_id, ts, duration: float, platform) -> None:
            # Any of these may be None or, for `ts`, a non-datetime string, to
            # exercise the DQ checks (null_* / invalid_timestamp).
            if ts is None:
                timestamp = None
            elif isinstance(ts, datetime):
                timestamp = _ts(ts)
            else:
                timestamp = ts  # already a string, e.g. "not-a-date"
            fh.write(json.dumps({
                "user_id": user_id, "timestamp": timestamp,
                "duration": duration, "platform": platform,
            }) + "\n")

        # Guaranteed multi-platform users (so the DAU-on-multiple-platforms
        # property is always observable in the sample).
        for i in range(100):
            user_id = f"user_{i:06d}"
            day0 = start_day.replace(hour=12)
            emit(user_id, day0, rng.uniform(60, 3600), "Windows")
            emit(user_id, day0 + timedelta(minutes=rng.randint(5, 120)), rng.uniform(60, 3600), "Android")

        for _ in range(sessions):
            # Skew toward a "heavy" subset of users (power-law-ish) to mimic
            # real usage and guarantee many multi-platform, multi-session days.
            idx = min(n_accounts - 1, int((rng.random() ** 2) * n_accounts))
            user_id = f"user_{idx:06d}"

            day_offset = rng.randrange(days)
            hour = rng.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]
            ts = start_day + timedelta(
                days=day_offset, hours=hour,
                minutes=rng.randint(0, 59), seconds=rng.randint(0, 59),
            )
            platform = _weighted_choice(rng, PLATFORMS, PLATFORM_WEIGHTS)
            duration = round(rng.uniform(5.0, 7200.0), 2)

            # Late-arriving: ~1% of events actually occurred 1-7 days earlier.
            if rng.random() < 0.01:
                ts -= timedelta(days=rng.randint(1, 7))

            emit(user_id, ts, duration, platform)
            # Exact duplicates: ~2% of events are re-emitted verbatim.
            if rng.random() < 0.02:
                emit(user_id, ts, duration, platform)
            # Same-day multi-platform: ~12% of sessions are followed by a second
            # session from the same user, the same day, on a different platform —
            # so DAU-on-multiple-platforms is observable throughout the range.
            elif rng.random() < 0.12:
                other = rng.choice([p for p in PLATFORMS if p != platform])
                emit(
                    user_id,
                    ts + timedelta(minutes=rng.randint(5, 300)),
                    round(rng.uniform(60.0, 3600.0), 2),
                    other,
                )

        # Orphan sessions: valid shape, but the user_id has no matching account,
        # so the join yields country 'UNKNOWN' (classified, not dropped).
        for _ in range(20):
            emit(
                "user_999999",
                start_day + timedelta(days=rng.randrange(days), hours=rng.randrange(24)),
                rng.uniform(60, 3600),
                _weighted_choice(rng, PLATFORMS, PLATFORM_WEIGHTS),
            )

        # Intentionally invalid records (quarantined by the DQ checks).
        for _ in range(40):
            emit(None, start_day, rng.uniform(60, 3600), "Windows")                       # null_user_id
            emit(f"user_{rng.randrange(n_accounts):06d}", None, rng.uniform(60, 3600), "Windows")  # null_timestamp
            emit(f"user_{rng.randrange(n_accounts):06d}", "not-a-date", rng.uniform(60, 3600), "Windows")  # invalid_timestamp
            emit(f"user_{rng.randrange(n_accounts):06d}", start_day, rng.uniform(60, 3600), None)  # null_platform
            emit(f"user_{rng.randrange(n_accounts):06d}", start_day, -rng.uniform(1, 3600), "Windows")  # negative_duration

    # --- Minute-level CCU (one day) ----------------------------------------
    ccu_path = out_dir / "detailed_ccu.csv"
    ccu_hourly = [
        800, 650, 550, 500, 520, 620, 900, 1300, 1600, 1800, 1900, 2000,
        2100, 2200, 2400, 2600, 2800, 3000, 3200, 3400, 3600, 3400, 2800, 1800,
    ]
    with ccu_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "ccu"])
        day0 = end.replace(hour=0, minute=0, second=0)
        for minute in range(1440):
            base = ccu_hourly[minute // 60]
            ccu = max(0, int(base + rng.gauss(0, 150)))
            writer.writerow([_ts(day0 + timedelta(minutes=minute)), ccu])

    return {"accounts": accounts_path, "sessions": sessions_path, "ccu": ccu_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the deterministic sample dataset.")
    parser.add_argument("--accounts", type=int, default=10_000)
    parser.add_argument("--sessions", type=int, default=500_000)
    parser.add_argument("--days", type=int, default=1095)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", type=Path, default=SAMPLE_DIR)
    args = parser.parse_args()

    paths = generate(
        accounts=args.accounts,
        sessions=args.sessions,
        days=args.days,
        end_date=args.end_date,
        seed=args.seed,
        out_dir=args.out_dir,
    )
    for name, path in paths.items():
        print(f"{name:9s} -> {path}")


if __name__ == "__main__":
    main()
