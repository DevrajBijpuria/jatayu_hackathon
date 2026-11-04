"""Phase 4 — Critic (Adversarial Agent).

The only function other phases may call is run().
See AGENTS.md §5.3 and §6 (Phase 4).
"""
from __future__ import annotations

from truthguard import config
from truthguard.contracts import TGState

from .baseline import run as _baseline_run
from .impl import run as _impl_run


def run(state: TGState) -> TGState:
    """Fill state.findings by adversarially checking state.draft."""
    if config.USE_BASELINE["critic"]:
        return _baseline_run(state)
    return _impl_run(state)
