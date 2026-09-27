"""Accounts extraction.

Production source: PostgreSQL ``accounts`` table.
Local mock: a CSV export of that table (same shape as ``COPY ... TO STDOUT``).

The pipeline only depends on :class:`AccountsSource`, so it is indifferent to
whether rows come from a real database or a local file.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterator

from .base import AccountsSource

ACCOUNT_FIELDS = ["user_id", "country", "created_at", "updated_at"]

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CsvAccountsSource(AccountsSource):
    """Local mock: reads an ``accounts`` CSV export."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def fetch_accounts(self) -> Iterator[dict]:
        with self.path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                yield row


class PostgresAccountsSource(AccountsSource):
    """Production adapter: streams ``accounts`` from PostgreSQL.

    Requires the optional ``psycopg`` dependency (``pip install -e '.[docker]'``)
    and a reachable PostgreSQL instance (see ``docker-compose.yml``). Uses a
    server-side cursor so a large account table is streamed, not buffered.
    """

    def __init__(
        self,
        host: str,
        port: int,
        dbname: str,
        user: str,
        password: str,
        table: str,
    ) -> None:
        if not _IDENTIFIER.match(table):
            raise ValueError(f"Invalid table name: {table!r}")
        self.host = host
        self.port = port
        self.dbname = dbname
        self.user = user
        self.password = password
        self.table = table

    def fetch_accounts(self) -> Iterator[dict]:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "psycopg is required to read from PostgreSQL. Install it with: "
                "pip install -e '.[docker]'"
            ) from exc

        with psycopg.connect(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=self.password,
        ) as conn:
            with conn.cursor(name="accounts_cursor") as cur:
                cur.itersize = 10_000
                cur.execute(
                    f"SELECT user_id, country, created_at, updated_at FROM {self.table}"
                )
                for user_id, country, created_at, updated_at in cur:
                    yield {
                        "user_id": user_id,
                        "country": country,
                        "created_at": created_at,
                        "updated_at": updated_at,
                    }
