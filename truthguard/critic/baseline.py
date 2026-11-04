"""Phase 4 baseline — returns no findings (pessimistically trusts the draft)."""
from __future__ import annotations

from truthguard.contracts import TGState


def run(state: TGState) -> TGState:
    # Baseline: no findings produced
    state.findings = []
    return state
