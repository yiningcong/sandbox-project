"""Pipeline orchestration + CLI.

Local-mock flow (no external services):

  PostgreSQL accounts (CSV export)  --extract-->  data/raw/accounts.csv
  Elasticsearch sessions (NDJSON)   --extract-->  data/raw/sessions.ndjson  (windowed)
        |
        v
  DuckDB (local BigQuery)  --transform-->  fact_daily_user_activity
        |
        +--> data/processed/fact_daily_user_activity.parquet
        +--> data/processed/fact_daily_user_activity.csv
        +--> data/processed/dq_report.json
        +--> DAU summary (printed)

Set ``POSTGRES_HOST`` / ``ELASTICSEARCH_URL`` to swap the local mocks for the
real services (see docs/architecture.md).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from src.config import Config, configure_logging
from src.ingestion.elasticsearch import ElasticsearchSessionsSource, NdjsonSessionsSource
from src.ingestion.postgres import CsvAccountsSource, PostgresAccountsSource
from src.transformation.daily_activity import DAUResult, TransformResult, query_dau, transform
from src.warehouse import create_schema, open_warehouse

log = logging.getLogger("pipeline")

ACCOUNT_FIELDS = ["user_id", "country", "created_at", "updated_at"]


@dataclass
class RunResult:
    accounts_extracted: int
    sessions_extracted: int
    transform: TransformResult
    dau: DAUResult


def _accounts_source(config: Config):
    if config.postgres_host:
        log.info("Using PostgreSQL accounts source (%s:%s)", config.postgres_host, config.postgres_port)
        return PostgresAccountsSource(
            host=config.postgres_host,
            port=config.postgres_port,
            dbname=config.postgres_db,
            user=config.postgres_user,
            password=config.postgres_password,
            table=config.postgres_accounts_table,
        )
    log.info("Using local mock accounts source (%s)", config.accounts_path)
    return CsvAccountsSource(config.accounts_path)


def _sessions_source(config: Config):
    if config.elasticsearch_url:
        log.info("Using Elasticsearch sessions source (%s)", config.elasticsearch_url)
        return ElasticsearchSessionsSource(config.elasticsearch_url, config.elasticsearch_index)
    log.info("Using local mock sessions source (%s)", config.sessions_path)
    return NdjsonSessionsSource(config.sessions_path)


def _extract(config: Config, accounts_src, sessions_src) -> tuple[Path, Path, int, int]:
    """Pull sources into the raw staging directory, windowed to the event time.

    This is the extract step; the range filter happens at the source so only the
    required time window (plus the reprocess window) is pulled — never 500M rows.
    """
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    accounts_raw = config.raw_dir / "accounts.csv"
    sessions_raw = config.raw_dir / "sessions.ndjson"

    start_dt = datetime.combine(date.fromisoformat(config.extract_start_date), time.min)
    end_dt = datetime.combine(date.fromisoformat(config.extract_end_date), time.min)

    n_accounts = 0
    with accounts_raw.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ACCOUNT_FIELDS)
        writer.writeheader()
        for row in accounts_src.fetch_accounts():
            writer.writerow({k: row.get(k) for k in ACCOUNT_FIELDS})
            n_accounts += 1

    n_sessions = 0
    with sessions_raw.open("w") as fh:
        for row in sessions_src.fetch_sessions(start_dt, end_dt):
            # serialization strings to disk
            fh.write(json.dumps(row) + "\n")
            n_sessions += 1

    return accounts_raw, sessions_raw, n_accounts, n_sessions

# Main Processing Engine
def run(config: Config) -> RunResult:
    accounts_src = _accounts_source(config)
    sessions_src = _sessions_source(config)

    log.info(
        "Extracting window [%s, %s) (reprocess window %d day(s))",
        config.extract_start_date, config.extract_end_date, config.reprocess_window_days,
    )
    # Triggers the downloading phase to fetch the raw data files.
    accounts_raw, sessions_raw, n_accounts, n_sessions = _extract(config, accounts_src, sessions_src)
    log.info("Extracted %d accounts, %d sessions", n_accounts, n_sessions)

    # Initializes a local DuckDB analytical database and builds fresh table blueprints
    conn = open_warehouse()
    create_schema(conn)
    
    # Triggers your data-cleaning steps, isolating bad rows into a quarantine status
    tresult = transform(conn, accounts_raw, sessions_raw)
    
    # Runs the final SQL metric queries to calculate unique user counts
    dau = query_dau(conn)

    # Persist outputs for inspection / downstream tools.
    config.processed_dir.mkdir(parents=True, exist_ok=True)
    fact_parquet = config.processed_dir / "fact_daily_user_activity.parquet"
    fact_csv = config.processed_dir / "fact_daily_user_activity.csv"
    dq_report = config.processed_dir / "dq_report.json"
    conn.execute(
        "COPY (SELECT * FROM fact_daily_user_activity ORDER BY activity_date, user_id, platform) "
        "TO ? (FORMAT parquet)", [str(fact_parquet)]
    )
    conn.execute(
        "COPY (SELECT * FROM fact_daily_user_activity ORDER BY activity_date, user_id, platform) "
        "TO ? (HEADER true)", [str(fact_csv)]
    )
    dq_report.write_text(json.dumps(asdict(tresult), indent=2, default=str) + "\n")
    conn.close()

    return RunResult(
        accounts_extracted=n_accounts,
        sessions_extracted=n_sessions,
        transform=tresult,
        dau=dau,
    )


def run_ccu(config: Config) -> list[tuple]:
    """Demo the hourly CCU query against the local minute-level CCU file."""
    conn = open_warehouse()
    conn.execute(
        "CREATE OR REPLACE TABLE _ccu AS "
        "SELECT * FROM read_csv_auto(?, header = true, "
        "columns = {'timestamp': 'VARCHAR', 'ccu': 'DOUBLE'})",
        [str(config.ccu_path)],
    )
    rows = conn.execute(
        "SELECT date_trunc('hour', CAST(\"timestamp\" AS TIMESTAMP)) AS hour, "
        "AVG(ccu) AS avg_ccu "
        "FROM _ccu GROUP BY 1 ORDER BY 1"
    ).fetchall()
    config.processed_dir.mkdir(parents=True, exist_ok=True)
    conn.execute(
        "COPY (SELECT date_trunc('hour', CAST(\"timestamp\" AS TIMESTAMP)) AS hour, "
        "AVG(ccu) AS avg_ccu "
        "FROM _ccu GROUP BY 1 ORDER BY 1) TO ? (HEADER true)",
        [str(config.processed_dir / "hourly_ccu.csv")],
    )
    conn.close()
    return rows


def _print_run(result: RunResult, config: Config) -> None:
    t = result.transform
    d = result.dau
    print("\n================== DAU pipeline summary ==================")
    print(f"Window                 : [{config.start_date}, {config.end_date}) "
          f"reprocess {config.reprocess_window_days}d")
    print(f"Accounts extracted     : {result.accounts_extracted:,}")
    print(f"Sessions extracted     : {result.sessions_extracted:,}")
    print(f"  valid                : {t.sessions_valid:,}")
    print(f"  quarantined          : {t.sessions_quarantined:,}")
    for reason, count in t.quarantine.items():
        print(f"    - {reason:20s} {count:,}")
    print(f"Fact rows (date/user/platform): {t.fact_rows:,}")
    print(f"Distinct users in range       : {d.dau_total:,}  (NOT a sum of DAU)")
    print(f"Average daily DAU             : {d.avg_daily_dau:,.1f}")
    print("\nDAU over time (last 5 days):")
    for day, dau in d.daily[-5:]:
        print(f"  {day}  {dau:,}")
    print("\nDAU by country (top 5):")
    for country, dau in d.by_country[:5]:
        print(f"  {country:3s}  {dau:,}")
    print("\nDAU by platform:")
    for platform, dau in d.by_platform:
        print(f"  {platform:10s}  {dau:,}")
    print("==========================================================\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="DAU ETL pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Extract + transform + query DAU")
    run_p.add_argument("--start-date", default=None, help="YYYY-MM-DD (defaults to env/30-day window)")
    run_p.add_argument("--end-date", default=None, help="YYYY-MM-DD (defaults to env)")
    run_p.add_argument("--reprocess-window", type=int, default=None, help="extra days before start-date")
    run_p.add_argument("--warehouse", default=None, help="DuckDB file path (default: in-memory)")

    ccu_p = sub.add_parser("ccu", help="Run the hourly CCU query")

    args = parser.parse_args(argv)

    config = Config.from_env()
    if getattr(args, "start_date", None) is not None:
        config.start_date = args.start_date
    if getattr(args, "end_date", None) is not None:
        config.end_date = args.end_date
    if getattr(args, "reprocess_window", None) is not None:
        config.reprocess_window_days = args.reprocess_window

    configure_logging(config.log_level)

    if args.command == "run":
        result = run(config)
        _print_run(result, config)
    elif args.command == "ccu":
        rows = run_ccu(config)
        print("\n================== hourly CCU (avg of minute-level) ==================")
        for hour, avg_ccu in rows:
            print(f"  {hour}  avg_ccu={avg_ccu:,.1f}")
        print("======================================================================\n")


if __name__ == "__main__":
    main()
