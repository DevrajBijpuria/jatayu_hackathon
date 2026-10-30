"""Phase 3 baseline — returns the top candidate's source_text as a single claim."""
from __future__ import annotations

from truthguard.contracts import Claim, Draft, TGState


def run(state: TGState) -> TGState:
    if state.retrieval is None or not state.retrieval.candidates:
        state.draft = Draft(
            answer_text="No relevant documents found.",
            claims=[],
        )
        return state

    top = state.retrieval.candidates[0]
    state.draft = Draft(
        answer_text=top.clause.source_text,
        claims=[
            Claim(
                claim_id="c1",
                text=top.clause.source_text,
                clause_ids=[top.clause.clause_id],
            )
        ],
    )
    return state
