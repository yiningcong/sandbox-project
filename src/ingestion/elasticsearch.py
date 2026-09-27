"""Sessions extraction.

Production source: Elasticsearch ``sessions`` index.
Local mock: an NDJSON file — the exact format Elasticsearch uses for bulk
exports (one JSON ``_source`` document per line).

The adapter applies the time-range filter itself so the prototype demonstrates
"extract only the required window" even though the local file holds full history.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .base import SessionsSource

# Source timestamps are assumed to be naive UTC (see docs/assumptions.md).
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"


def parse_utc(value: object) -> datetime | None:
    """Parse a UTC timestamp string; ``None`` if absent or malformed."""
    if value is None:
        return None
    try:
        return datetime.strptime(str(value), TIMESTAMP_FORMAT)
    except (ValueError, TypeError):
        return None


class NdjsonSessionsSource(SessionsSource):
    """Local mock: reads an NDJSON of session ``_source`` documents."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def fetch_sessions(self, start: datetime, end: datetime) -> Iterator[dict]:
        with self.path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                ts = parse_utc(record.get("timestamp"))
                # Range filter mirrors the Elasticsearch range query pushed down
                # to the source. Rows whose timestamp cannot be parsed are let
                # through so the DQ layer can quarantine them (in a real ES
                # index the field would be a `date` type, so malformed values
                # could not exist at all).
                if ts is None or (start <= ts < end):
                    yield record


class ElasticsearchSessionsSource(SessionsSource):
    """Production adapter: scrolls the ``sessions`` index by time range.

    Requires the optional ``elasticsearch`` dependency and a reachable cluster.
    """

    def __init__(self, url: str, index: str) -> None:
        self.url = url
        self.index = index

    def fetch_sessions(self, start: datetime, end: datetime) -> Iterator[dict]:
        try:
            from elasticsearch import Elasticsearch
            from elasticsearch.helpers import scan
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "The `elasticsearch` package is required to read sessions from "
                "Elasticsearch. Install it with: pip install -e '.[docker]'"
            ) from exc

        client = Elasticsearch(self.url)
        query = {
            "query": {
                "range": {
                    "timestamp": {
                        "gte": start.isoformat(),
                        "lt": end.isoformat(),
                    }
                }
            },
            "_source": ["user_id", "timestamp", "duration", "platform"],
        }
        # Scroll for memory-efficient full-window extraction.
        for hit in scan(client, index=self.index, query=query, size=1000):
            yield hit["_source"]
