"""Connectors — base class and state helpers (behind ENABLE_CONNECTORS)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime


class BaseConnector(ABC):
    name: str = "base"

    @abstractmethod
    def sync(self, conn) -> list[str]:
        """Download new files and ingest them. Returns list of ingested doc_ids."""

    def _update_state(self, conn, cursor: str, status: str) -> None:
        conn.execute(
            """
            INSERT INTO connector_state (connector, cursor, last_run_at, last_status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (connector) DO UPDATE SET
                cursor = excluded.cursor,
                last_run_at = excluded.last_run_at,
                last_status = excluded.last_status
            """,
            [self.name, cursor, datetime.now(tz=UTC).isoformat(), status],
        )

    def _get_cursor(self, conn) -> str | None:
        row = conn.execute(
            "SELECT cursor FROM connector_state WHERE connector = ?", [self.name]
        ).fetchone()
        return row[0] if row else None
