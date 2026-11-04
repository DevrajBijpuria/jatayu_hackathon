"""FolderConnector — watches a local directory for new/updated files."""
from __future__ import annotations

import os
from pathlib import Path

from truthguard import config
from truthguard.connectors import BaseConnector

_SUPPORTED = {".txt", ".pdf", ".docx", ".doc", ".eml"}


class FolderConnector(BaseConnector):
    name = "folder"

    def __init__(self, watch_dir: str | None = None) -> None:
        self.watch_dir = Path(watch_dir or config.INBOX_DIR)

    def sync(self, conn) -> list[str]:
        if not self.watch_dir.is_dir():
            self._update_state(conn, "", "error:dir_missing")
            return []

        cursor_str = self._get_cursor(conn)
        last_mtime = float(cursor_str) if cursor_str else 0.0

        new_max_mtime = last_mtime
        to_ingest: list[str] = []

        try:
            for entry in os.scandir(self.watch_dir):
                if not entry.is_file():
                    continue
                if Path(entry.name).suffix.lower() not in _SUPPORTED:
                    continue
                mtime = entry.stat().st_mtime
                if mtime > last_mtime:
                    to_ingest.append(entry.path)
                    if mtime > new_max_mtime:
                        new_max_mtime = mtime
        except OSError as exc:
            self._update_state(conn, cursor_str or "", f"error:{exc}")
            return []

        doc_ids: list[str] = []
        if to_ingest:
            from truthguard.ingest import run as ingest_run
            try:
                doc_ids = ingest_run(to_ingest)
            except Exception as exc:
                self._update_state(conn, cursor_str or "", f"error:{exc}")
                return []

        self._update_state(conn, str(new_max_mtime), "ok")
        return doc_ids
