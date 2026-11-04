"""DuckDB connection helper — creates the schema on first use."""
from __future__ import annotations

from pathlib import Path
from threading import Lock

import duckdb

from truthguard.config import DUCKDB_PATH

_lock = Lock()
_conn: duckdb.DuckDBPyConnection | None = None

_SCHEMA_SQL = Path(__file__).parent / "schema.sql"


def get_conn() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is not None:
        return _conn
    with _lock:
        if _conn is not None:
            return _conn
        Path(DUCKDB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = duckdb.connect(DUCKDB_PATH)
        _conn.execute(_SCHEMA_SQL.read_text(encoding="utf-8"))
    return _conn


def reset_conn() -> None:
    """Close and reset the connection (used in tests)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
