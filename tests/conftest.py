"""Shared test fixtures."""
from __future__ import annotations

import os

import pytest

# Use an in-memory DuckDB for all tests so they don't touch the real data dir.
os.environ.setdefault("DUCKDB_PATH", ":memory:")
os.environ.setdefault("BASELINE_INGEST", "true")
os.environ.setdefault("BASELINE_RETRIEVE", "true")
os.environ.setdefault("BASELINE_SYNTHESIZE", "true")
os.environ.setdefault("BASELINE_CRITIC", "true")
os.environ.setdefault("BASELINE_RESOLVE", "true")


@pytest.fixture(autouse=True)
def reset_db():
    """Reset the DuckDB connection before each test."""
    from truthguard.db.conn import reset_conn
    reset_conn()
    yield
    reset_conn()


@pytest.fixture
def tmp_txt(tmp_path):
    """Return a factory that creates named .txt files in a temp directory."""
    def _make(name: str, content: str):
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return str(p)
    return _make
