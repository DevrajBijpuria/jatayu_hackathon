"""Smoke test for Phase 5 baseline."""
from __future__ import annotations

from truthguard.contracts import (
    Claim,
    Clause,
    Draft,
    RetrievalResult,
    RetrievedClause,
    Status,
    TGState,
    User,
)
from truthguard.resolve import run as resolve_run


def _employee() -> User:
    return User(user_id="u1", role="employee", access_levels=["all"])


def _make_state(source_text: str = "Limit is $5,000.") -> TGState:
    clause = Clause(clause_id="DOC#1", doc_id="DOC", source_text=source_text)
    rc = RetrievedClause(clause=clause, score=1.0, via="search")
    return TGState(
        question="What is the limit?",
        user=_employee(),
        retrieval=RetrievalResult(concept_id=None, candidates=[rc], family=[rc]),
        draft=Draft(
            answer_text=source_text,
            claims=[Claim(claim_id="c1", text=source_text, clause_ids=["DOC#1"])],
        ),
    )


def test_no_findings_returns_supported():
    state = _make_state()
    state = resolve_run(state)

    assert state.verdict is not None
    assert state.verdict.status == Status.SUPPORTED


def test_verdict_has_shown_sources():
    state = _make_state()
    state = resolve_run(state)

    assert "DOC#1" in state.verdict.shown_sources


def test_no_draft_returns_unresolved():
    state = TGState(
        question="Anything?",
        user=_employee(),
        retrieval=RetrievalResult(concept_id=None, candidates=[], family=[]),
    )
    state = resolve_run(state)

    assert state.verdict is not None
    assert state.verdict.status == Status.UNRESOLVED
