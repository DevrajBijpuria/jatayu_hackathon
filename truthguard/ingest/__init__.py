"""Phase 1 — Ingest & Conflict Index.

The only function other phases may call is run().
See AGENTS.md §5.3 and §6 (Phase 1).
"""
from __future__ import annotations

from truthguard import config

from .baseline import run as _baseline_run
from .impl import run as _impl_run


def run(paths: list[str], access_level: str = "all", force: bool = False) -> list[str]:
    """Ingest files at *paths* and return the list of doc_ids created."""
    if config.USE_BASELINE["ingest"]:
        return _baseline_run(paths, access_level)
    return _impl_run(paths, access_level, force=force)
