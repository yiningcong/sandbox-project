"""Shared fixtures: an in-memory DuckDB warehouse and temp source-file helpers."""
from __future__ import annotations

import json

import pytest

from src.transformation.daily_activity import query_dau, transform
from src.warehouse import create_schema, open_warehouse


@pytest.fixture
def warehouse():
    conn = open_warehouse()
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def make_sources(tmp_path):
    """Return a factory writing accounts CSV + sessions NDJSON into a temp dir."""

    def _make(accounts_rows: list[dict], session_rows: list[dict]):
        acc_path = tmp_path / "accounts.csv"
        with acc_path.open("w") as fh:
            fh.write("user_id,country,created_at,updated_at\n")
            for r in accounts_rows:
                fh.write(
                    f"{r['user_id']},{r['country']},"
                    f"2026-01-01T00:00:00,2026-01-01T00:00:00\n"
                )
        sess_path = tmp_path / "sessions.ndjson"
        with sess_path.open("w") as fh:
            for r in session_rows:
                fh.write(json.dumps(r) + "\n")
        return acc_path, sess_path

    return _make


@pytest.fixture
def run_transform(warehouse, make_sources):
    """Run the transform end-to-end and return (TransformResult, DAUResult)."""

    def _run(accounts_rows, session_rows):
        acc, sess = make_sources(accounts_rows, session_rows)
        tresult = transform(warehouse, acc, sess)
        return tresult, query_dau(warehouse)

    return _run
