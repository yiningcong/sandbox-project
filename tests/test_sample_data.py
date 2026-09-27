"""Sample-data generator: reproducibility (deterministic RNG seed)."""
from __future__ import annotations

import hashlib

from src.sample_data import generate


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generation_is_deterministic(tmp_path):
    a = generate(accounts=50, sessions=200, days=3, end_date="2026-09-23", seed=7, out_dir=tmp_path / "a")
    b = generate(accounts=50, sessions=200, days=3, end_date="2026-09-23", seed=7, out_dir=tmp_path / "b")
    for name in ("accounts", "sessions", "ccu"):
        assert _digest(a[name]) == _digest(b[name]), name


def test_different_seed_produces_different_data(tmp_path):
    a = generate(accounts=50, sessions=200, days=3, end_date="2026-09-23", seed=1, out_dir=tmp_path / "a")
    b = generate(accounts=50, sessions=200, days=3, end_date="2026-09-23", seed=2, out_dir=tmp_path / "b")
    assert _digest(a["sessions"]) != _digest(b["sessions"])
