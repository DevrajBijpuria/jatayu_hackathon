"""Smoke test for Phase 3 baseline."""
from __future__ import annotations

from truthguard.contracts import (
    Clause,
    RetrievalResult,
    RetrievedClause,
    TGState,
    User,
)
from truthguard.synthesize import run as synthesize_run


def _employee() -> User:
    return User(user_id="u1", role="employee", access_levels=["all"])


def _make_state_with_retrieval(source_text: str) -> TGState:
    clause = Clause(clause_id="DOC#1", doc_id="DOC", source_text=source_text)
    rc = RetrievedClause(clause=clause, score=1.0, via="search")
    return TGState(
        question="What is the limit?",
        user=_employee(),
        retrieval=RetrievalResult(concept_id=None, candidates=[rc], family=[rc]),
    )


def test_synthesize_produces_draft():
    state = _make_state_with_retrieval("Managers may approve up to $5,000.")
    state = synthesize_run(state)

    assert state.draft is not None
    assert state.draft.answer_text != ""
    assert len(state.draft.claims) >= 1


def test_synthesize_claims_cite_retrieved_clause():
    state = _make_state_with_retrieval("Managers may approve up to $5,000.")
    state = synthesize_run(state)

    for claim in state.draft.claims:
        assert len(claim.clause_ids) > 0, "Claim has no clause_ids"
        for cid in claim.clause_ids:
            assert cid == "DOC#1", f"Claim cites unretrieved clause: {cid}"


def test_synthesize_empty_retrieval():
    state = TGState(
        question="What is the limit?",
        user=_employee(),
        retrieval=RetrievalResult(concept_id=None, candidates=[], family=[]),
    )
    state = synthesize_run(state)

    assert state.draft is not None
    # Baseline returns "No relevant documents found." with no claims
    assert state.draft.claims == [] or state.draft.answer_text != ""
