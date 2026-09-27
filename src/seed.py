"""Seed the optional real services from the deterministic sample data.

The local prototype normally reads ``data/sample/accounts.csv`` and
``data/sample/sessions.ndjson``. Those files are, by convention, *exports* of the
production tables (the accounts CSV is the shape of ``COPY ... TO STDOUT``; the
sessions NDJSON is Elasticsearch's own bulk ``_source`` format). This module loads
those same exports back into live services so the pipeline can run against them
instead of the local files:

    docker compose up -d
    make docker-setup
    export POSTGRES_HOST=localhost ELASTICSEARCH_URL=http://localhost:9200
    make seed
    make run

Which services get seeded is driven by the same env vars the pipeline uses:

  * ``POSTGRES_HOST``     -> load accounts into PostgreSQL
  * ``ELASTICSEARCH_URL`` -> index sessions into Elasticsearch

The seed is idempotent (truncate + reload / re-create + re-index).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

from src.config import Config, configure_logging

# Matches docker/postgres/init.sql (single source of truth for the table shape).
ACCOUNTS_DDL = """
CREATE TABLE IF NOT EXISTS accounts (
    user_id    TEXT PRIMARY KEY,
    country    TEXT,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
)
"""

# Only ``timestamp`` must be a real ``date`` type (the sessions adapter range-filters
# on it). The others are keyword/float so no dynamic text analysis is applied.
SESSIONS_MAPPING = {
    "properties": {
        "user_id": {"type": "keyword"},
        "timestamp": {"type": "date"},
        "duration": {"type": "float"},
        "platform": {"type": "keyword"},
    }
}

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"


def seed_postgres(config: Config) -> int:
    """Load accounts.csv into the ``accounts`` table. Returns the row count."""
    import psycopg

    with psycopg.connect(
        host=config.postgres_host,
        port=config.postgres_port,
        dbname=config.postgres_db,
        user=config.postgres_user,
        password=config.postgres_password,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(ACCOUNTS_DDL)
            cur.execute("TRUNCATE accounts")
            with cur.copy(
                "COPY accounts (user_id, country, created_at, updated_at) "
                "FROM STDIN WITH (FORMAT csv, HEADER true)"
            ) as copy:
                with config.accounts_path.open("rb") as fh:
                    while chunk := fh.read(1 << 16):
                        copy.write(chunk)
            cur.execute("SELECT COUNT(*) FROM accounts")
            return cur.fetchone()[0]


def _valid_session(rec: dict) -> bool:
    """A real ES ``date``-typed index cannot hold malformed records; drop them here.

    The local NDJSON mock deliberately contains invalid rows (null ids, malformed
    timestamps, negative durations) to exercise the DQ layer. Those rows can't be
    represented in a typed index, so they are not seeded.
    """
    ts = rec.get("timestamp")
    if not isinstance(ts, str):
        return False
    try:
        datetime.strptime(ts, TIMESTAMP_FORMAT)
    except ValueError:
        return False
    if not isinstance(rec.get("user_id"), str) or not rec["user_id"]:
        return False
    if not isinstance(rec.get("platform"), str) or not rec["platform"]:
        return False
    duration = rec.get("duration")
    if not isinstance(duration, (int, float)) or duration < 0:
        return False
    return True


def seed_elasticsearch(config: Config) -> int:
    """Bulk-index the valid sessions into the ``sessions`` index. Returns docs indexed."""
    from elasticsearch import Elasticsearch
    from elasticsearch.helpers import bulk

    client = Elasticsearch(config.elasticsearch_url)
    index = config.elasticsearch_index
    if not client.indices.exists(index=index):
        client.indices.create(index=index, mappings=SESSIONS_MAPPING)

    def actions():
        with config.sessions_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if not _valid_session(rec):
                    continue
                yield {"_index": index, "_source": rec}

    success, errors = bulk(
        client, actions(), chunk_size=1000, request_timeout=120, raise_on_error=False
    )
    if errors:
        print(f"WARNING: {len(errors)} session(s) failed to index", file=sys.stderr)
    return success


def main() -> None:
    config = Config.from_env()
    configure_logging(config.log_level)

    done = []
    if config.postgres_host:
        n = seed_postgres(config)
        done.append(f"postgres accounts: {n:,} rows -> {config.postgres_host}:{config.postgres_port}/{config.postgres_db}")
    if config.elasticsearch_url:
        n = seed_elasticsearch(config)
        done.append(f"elasticsearch sessions: {n:,} docs -> {config.elasticsearch_url}/{config.elasticsearch_index}")

    if not done:
        print(
            "No services configured to seed. Set POSTGRES_HOST and/or ELASTICSEARCH_URL.\n"
            "\nExample:\n"
            "  docker compose up -d\n"
            "  export POSTGRES_HOST=localhost ELASTICSEARCH_URL=http://localhost:9200\n"
            "  make seed\n"
        )
        sys.exit(1)

    for line in done:
        print(f"seeded {line}")


if __name__ == "__main__":
    main()
