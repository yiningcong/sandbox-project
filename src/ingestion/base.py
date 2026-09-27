"""Interfaces for source extraction.

Each production source has two implementations sharing one interface:

  * a *local mock* (no external services required) used by the prototype,
  * a *production* adapter that talks to the real service.

The pipeline depends only on these interfaces, so it is agnostic to whether a
row came from a real database or a local file.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterator, Protocol


class AccountsSource(Protocol):
    """Extracts account rows: ``{user_id, country, created_at, updated_at}``."""

    def fetch_accounts(self) -> Iterator[dict]:
        ...


class SessionsSource(Protocol):
    """Extracts session rows: ``{user_id, timestamp, duration, platform}``.

    ``start``/``end`` are *inclusive* event-time bounds (UTC, naive) so callers
    can request an incremental window rather than the whole history.
    """

    def fetch_sessions(self, start: datetime, end: datetime) -> Iterator[dict]:
        ...
