"""Central configuration for the DAU ETL prototype.

Configuration comes from environment variables (see ``.env.example``) so the
same code runs in local-mock mode (no external services) or against real
PostgreSQL / Elasticsearch by simply setting a host/URL.

All dates and timestamps are UTC (see docs/assumptions.md).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

# Defaults match the sample-data generator (src/sample_data.py).
DEFAULT_END_DATE = "2026-09-23"
DEFAULT_WINDOW_DAYS = 30

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    # --- Sources ---
    accounts_path: Path
    sessions_path: Path
    ccu_path: Path
    postgres_host: str | None
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_accounts_table: str
    elasticsearch_url: str | None
    elasticsearch_index: str

    # --- Pipeline window (all UTC, inclusive start / exclusive end) ---
    start_date: str
    end_date: str
    reprocess_window_days: int

    # --- Directories ---
    raw_dir: Path
    processed_dir: Path

    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Config":
        env = os.environ if env is None else env

        end_date = env.get("PIPELINE_END_DATE", DEFAULT_END_DATE)
        start_date = env.get("PIPELINE_START_DATE") or (
            (date.fromisoformat(end_date) - timedelta(days=DEFAULT_WINDOW_DAYS - 1)).isoformat()
        )

        return cls(
            accounts_path=Path(env.get("ACCOUNTS_PATH", PROJECT_ROOT / "data" / "sample" / "accounts.csv")),
            sessions_path=Path(env.get("SESSIONS_PATH", PROJECT_ROOT / "data" / "sample" / "sessions.ndjson")),
            ccu_path=Path(env.get("CCU_PATH", PROJECT_ROOT / "data" / "sample" / "detailed_ccu.csv")),
            postgres_host=env.get("POSTGRES_HOST") or None,
            postgres_port=int(env.get("POSTGRES_PORT", "5432")),
            postgres_db=env.get("POSTGRES_DB", "accounts"),
            postgres_user=env.get("POSTGRES_USER", "etl"),
            postgres_password=env.get("POSTGRES_PASSWORD", ""),
            postgres_accounts_table=env.get("POSTGRES_ACCOUNTS_TABLE", "accounts"),
            elasticsearch_url=env.get("ELASTICSEARCH_URL") or None,
            elasticsearch_index=env.get("ELASTICSEARCH_INDEX", "sessions"),
            start_date=start_date,
            end_date=end_date,
            reprocess_window_days=int(env.get("REPROCESS_WINDOW_DAYS", "7")),
            raw_dir=Path(env.get("RAW_DIR", PROJECT_ROOT / "data" / "raw")),
            processed_dir=Path(env.get("PROCESSED_DIR", PROJECT_ROOT / "data" / "processed")),
            log_level=env.get("LOG_LEVEL", "INFO"),
        )

    @property
    def extract_start_date(self) -> str:
        """Lower bound (inclusive) of the extraction window.

        Includes ``reprocess_window_days`` of history before ``start_date`` so
        late-arriving events are picked up without reprocessing everything.
        """
        return (date.fromisoformat(self.start_date) - timedelta(days=self.reprocess_window_days)).isoformat()

    @property
    def extract_end_date(self) -> str:
        """Upper bound (exclusive) of the extraction window."""
        return (date.fromisoformat(self.end_date) + timedelta(days=1)).isoformat()


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
