"""Phase 2 — Family-Aware Retriever.

The only function other phases may call is run().
See AGENTS.md §5.3 and §6 (Phase 2).
"""
from __future__ import annotations

from truthguard import config
from truthguard.contracts import TGState

from .baseline import run as _baseline_run
from .impl import run as _impl_run


def run(state: TGState) -> TGState:
    """Fill state.rewrites, state.as_of, and state.retrieval."""
    if config.USE_BASELINE["retrieve"]:
        return _baseline_run(state)
    return _impl_run(state)
