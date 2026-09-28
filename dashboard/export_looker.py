"""Export the two CSV files Looker Studio can actually consume.

Looker Studio cannot read local files (Parquet / DuckDB / HTML). Its
no-credentials path is Google Sheets: upload these CSVs to a sheet, then connect
Looker Studio's Google Sheets connector. The production path (BigQuery) is
documented in ``docs/looker-studio.md``; the data is identical in both.

Produces, under ``looker_studio/``:

  * ``fact_daily_user_activity.csv`` — ``(activity_date, user_id, country, platform)``
    the exact grain Looker Studio needs for ``COUNT_DISTINCT(user_id)`` to stay
    correct when filtering by country and/or platform. This is the fact table, NOT
    an aggregation: DAU is non-additive across platforms, so a pre-aggregated cube
    would give wrong numbers once a platform filter is applied.
  * ``hourly_ccu.csv`` — ``(timestamp, avg_ccu)`` one sample day's hour-level CCU,
    averaged from the minute detail.

Run: ``make looker-export`` (or ``.venv/bin/python dashboard/export_looker.py``)
after ``make sample-data && make run``.
"""
from __future__ import annotations

import csv
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
FACT = ROOT / "data" / "processed" / "fact_daily_user_activity.parquet"
DETAILED_CCU = ROOT / "data" / "sample" / "detailed_ccu.csv"

OUT_DIR = ROOT / "looker_studio"
OUT_FACT = OUT_DIR / "fact_daily_user_activity.csv"
OUT_CCU = OUT_DIR / "hourly_ccu.csv"


def main() -> None:
    if not FACT.exists():
        raise SystemExit(
            f"{FACT} not found — run `make sample-data && make run` first."
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(":memory:")
    conn.execute("SET TimeZone = 'UTC'")

    # 1. Fact table — deterministic ordering so the export is reproducible. DuckDB
    #    computes the ordering; Python streams the rows to CSV (COPY ... TO does not
    #    take a parameterized destination).
    fact_rows = 0
    with OUT_FACT.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["activity_date", "user_id", "country", "platform"])
        cur = conn.execute(
            "SELECT activity_date::VARCHAR, user_id, country, platform "
            "FROM read_parquet(?) ORDER BY activity_date, user_id, platform",
            [str(FACT)],
        )
        for row in cur.fetchall():
            w.writerow(row)
            fact_rows += 1

    # 2. Hourly CCU — average the minute-level detail to the hour (the documented
    #    "CCU per hour" definition; peak = MAX is the alternative).
    ccu_rows = conn.execute(
        "SELECT date_trunc('hour', CAST(timestamp AS TIMESTAMP)) AS h, AVG(ccu) "
        "FROM read_csv_auto(?, header = true, "
        "columns = {'timestamp': 'VARCHAR', 'ccu': 'DOUBLE'}) "
        "GROUP BY 1 ORDER BY 1",
        [str(DETAILED_CCU)],
    ).fetchall()
    with OUT_CCU.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "avg_ccu"])
        for h, v in ccu_rows:
            w.writerow([h.strftime("%Y-%m-%d %H:%M:%S"), round(v, 2)])
    conn.close()

    print(f"fact rows  : {fact_rows:,} -> {OUT_FACT}")
    print(f"ccu hours  : {len(ccu_rows):,}  -> {OUT_CCU}")
    print("\nNext: upload both files to Google Sheets, then follow")
    print("docs/looker-studio.md to connect Looker Studio.")


if __name__ == "__main__":
    main()
