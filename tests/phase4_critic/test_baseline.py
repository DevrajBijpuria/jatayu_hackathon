"""Smoke test for Phase 4 baseline."""
from __future__ import annotations

from truthguard.contracts import (
    Claim,
    Clause,
    Draft,
    RetrievalResult,
    RetrievedClause,
    TGState,
    User,
)
from truthguard.critic import run as critic_run


def _employee() -> User:
    return User(user_id="u1", role="employee", access_levels=["all"])


def _make_state() -> TGState:
    clause = Clause(clause_id="DOC#1", doc_id="DOC", source_text="Limit is $5,000.")
    rc = RetrievedClause(clause=clause, score=1.0, via="search")
    return TGState(
        question="What is the limit?",
        user=_employee(),
        retrieval=RetrievalResult(concept_id=None, candidates=[rc], family=[rc]),
        draft=Draft(
            answer_text="Limit is $5,000.",
            claims=[Claim(claim_id="c1", text="Limit is $5,000.", clause_ids=["DOC#1"])],
        ),
    )


def test_baseline_returns_no_findings():
    state = _make_state()
    state = critic_run(state)
    assert state.findings == []
