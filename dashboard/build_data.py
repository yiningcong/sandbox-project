"""Build the dashboard dataset and inject it into the HTML.

Reads the transformed fact table (``data/processed/fact_daily_user_activity.parquet``)
and the minute-level CCU sample (``data/sample/detailed_ccu.csv``), aggregates them
into the cubes the dashboard needs, and writes:

  * ``dashboard/data.json``   — the aggregate cubes (aligned to one date axis)
  * ``dashboard/index.html``  — ``template.html`` with the JSON injected

Run it with ``make dashboard`` (or ``.venv/bin/python dashboard/build_data.py``)
after ``make sample-data && make run`` (run the pipeline over the full range).

The cubes are aligned to a single date axis (``dates``) so the front end can slice
any date range with plain array indexing. Daily distinct counts are pre-aggregated
per (country, platform) because DAU is a non-additive COUNT(DISTINCT) that cannot
be derived from totals after filtering.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
FACT = ROOT / "data" / "processed" / "fact_daily_user_activity.parquet"
CCU = ROOT / "data" / "sample" / "detailed_ccu.csv"

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
OUT_HTML = HERE / "index.html"
OUT_JSON = HERE / "data.json"

COUNTRY_ORDER = ["US", "DE", "GB", "JP", "BR", "FR", "KR", "IN", "CA", "AU"]
PLATFORM_ORDER = ["Windows", "Android", "iOS"]


def main() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute("SET TimeZone = 'UTC'")

    conn.execute(
        "CREATE TABLE fact AS "
        "SELECT activity_date, user_id, country, platform FROM read_parquet(?)",
        [str(FACT)],
    )

    dates = [
        r[0].strftime("%Y-%m-%d")
        for r in conn.execute("SELECT DISTINCT activity_date FROM fact ORDER BY 1").fetchall()
    ]
    idx = {d: i for i, d in enumerate(dates)}
    n = len(dates)

    def aligned(rows) -> list[int]:
        out = [0] * n
        for d, v in rows:
            key = d if isinstance(d, str) else d.strftime("%Y-%m-%d")
            out[idx[key]] = int(v)
        return out

    daily = aligned(
        conn.execute(
            "SELECT activity_date, COUNT(DISTINCT user_id) FROM fact GROUP BY 1 ORDER BY 1"
        ).fetchall()
    )

    daily_by_country: dict[str, dict[str, int]] = {}
    for c, d, v in conn.execute(
        "SELECT country, activity_date, COUNT(DISTINCT user_id) FROM fact GROUP BY 1, 2"
    ).fetchall():
        daily_by_country.setdefault(c, {})[d.strftime("%Y-%m-%d")] = int(v)

    daily_by_platform: dict[str, dict[str, int]] = {}
    for p, d, v in conn.execute(
        "SELECT platform, activity_date, COUNT(DISTINCT user_id) FROM fact GROUP BY 1, 2"
    ).fetchall():
        daily_by_platform.setdefault(p, {})[d.strftime("%Y-%m-%d")] = int(v)

    daily_by_cp: dict[str, dict[str, dict[str, int]]] = {}
    for c, p, d, v in conn.execute(
        "SELECT country, platform, activity_date, COUNT(DISTINCT user_id) "
        "FROM fact GROUP BY 1, 2, 3"
    ).fetchall():
        daily_by_cp.setdefault(c, {}).setdefault(p, {})[d.strftime("%Y-%m-%d")] = int(v)

    by_country = [
        [c, int(v)]
        for c, v in conn.execute(
            "SELECT country, COUNT(DISTINCT user_id) FROM fact "
            "WHERE country <> 'UNKNOWN' GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    ]
    by_platform = [
        [p, int(v)]
        for p, v in conn.execute(
            "SELECT platform, COUNT(DISTINCT user_id) FROM fact GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    ]
    unknown_users = int(
        conn.execute("SELECT COUNT(DISTINCT user_id) FROM fact WHERE country = 'UNKNOWN'").fetchone()[0]
    )
    total_users = int(conn.execute("SELECT COUNT(DISTINCT user_id) FROM fact").fetchone()[0])

    # Hourly CCU (average of the minute-level detail), one sample day.
    ccu = [
        [h.strftime("%H:%M"), round(v, 1)]
        for h, v in conn.execute(
            "SELECT date_trunc('hour', CAST(timestamp AS TIMESTAMP)) AS h, AVG(ccu) "
            "FROM read_csv_auto(?, header = true, "
            "columns = {'timestamp': 'VARCHAR', 'ccu': 'DOUBLE'}) "
            "GROUP BY 1 ORDER BY 1",
            [str(CCU)],
        ).fetchall()
    ]
    peak_ccu = max(ccu, key=lambda r: r[1])
    conn.close()

    data = {
        "meta": {
            "min_date": dates[0],
            "max_date": dates[-1],
            "n_days": n,
            "total_users": total_users,
            "unknown_users": unknown_users,
            "peak_ccu": peak_ccu,
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "dates": dates,
        "daily": daily,
        "dailyByCountry": {
            c: aligned([(d, v) for d, v in m.items()]) for c, m in daily_by_country.items()
        },
        "dailyByPlatform": {
            p: aligned([(d, v) for d, v in m.items()]) for p, m in daily_by_platform.items()
        },
        "dailyByCountryPlatform": {
            c: {
                p: aligned([(d, v) for d, v in m.items()]) for p, m in byp.items()
            }
            for c, byp in daily_by_cp.items()
        },
        "byCountry": by_country,
        "byPlatform": by_platform,
        "countries": [c for c in COUNTRY_ORDER if c in daily_by_country],
        "platforms": PLATFORM_ORDER,
        "ccu": ccu,
    }

    payload = json.dumps(data, separators=(",", ":"))

    OUT_JSON.write_text(json.dumps(data) + "\n")

    template = TEMPLATE.read_text()
    if "__DATA_JSON__" not in template:
        raise SystemExit("template.html is missing the __DATA_JSON__ placeholder")
    OUT_HTML.write_text(template.replace("__DATA_JSON__", payload))

    print(f"dates      : {n} ({dates[0]} .. {dates[-1]})")
    print(f"users      : {total_users:,} distinct ({unknown_users} UNKNOWN)")
    print(f"peak CCU   : {peak_ccu[1]:,.0f} at {peak_ccu[0]}")
    print(f"json size  : {len(payload):,} bytes")
    print(f"wrote      : {OUT_HTML} ({OUT_HTML.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
