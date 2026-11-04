"""Round-trip tests for contracts.py."""
from __future__ import annotations

import json
from datetime import date

from truthguard.contracts import (
    Claim,
    Clause,
    Draft,
    Finding,
    FindingType,
    RetrievalResult,
    RetrievedClause,
    Status,
    TGState,
    User,
    Verdict,
)


def _make_user() -> User:
    return User(user_id="u1", name="Alice", role="employee", access_levels=["all"])


def _make_clause() -> Clause:
    return Clause(
        clause_id="DOC#1",
        doc_id="DOC",
        source_text="Managers may approve expenses up to $5,000.",
        effective_date=date(2023, 1, 15),
    )


def test_user_round_trip():
    u = _make_user()
    assert User.model_validate(json.loads(u.model_dump_json())) == u


def test_clause_round_trip():
    c = _make_clause()
    assert Clause.model_validate(json.loads(c.model_dump_json())) == c


def test_tgstate_round_trip():
    clause = _make_clause()
    rc = RetrievedClause(clause=clause, score=0.9, via="search")
    state = TGState(
        question="What is the limit?",
        user=_make_user(),
        as_of=date(2024, 1, 1),
        retrieval=RetrievalResult(
            concept_id="approval_limit",
            candidates=[rc],
            family=[rc],
        ),
        draft=Draft(
            answer_text="$5,000",
            claims=[Claim(claim_id="c1", text="$5,000", clause_ids=["DOC#1"])],
        ),
        findings=[
            Finding(
                type=FindingType.CONTRADICTION,
                claim_id="c1",
                clause_ids=["DOC#1"],
                detail="test",
            )
        ],
        verdict=Verdict(
            status=Status.SUPPORTED,
            answer_text="$5,000",
            applies=["DOC#1"],
            shown_sources=["DOC#1"],
            decisions=[],
        ),
    )
    restored = TGState.model_validate(json.loads(state.model_dump_json()))
    assert restored.question == state.question
    assert restored.verdict.status == Status.SUPPORTED
    assert restored.retrieval.concept_id == "approval_limit"
    assert restored.findings[0].type == FindingType.CONTRADICTION


def test_status_enum_values():
    assert Status.SUPPORTED.value == "SUPPORTED"
    assert Status.CONFLICT_RESOLVED.value == "CONFLICT_RESOLVED"
    assert Status.RESOLVED_BY_SCOPE.value == "RESOLVED_BY_SCOPE"
    assert Status.UNRESOLVED.value == "UNRESOLVED"


def test_finding_type_values():
    assert FindingType.CONTRADICTION.value == "contradiction"
    assert FindingType.STALE.value == "stale"
    assert FindingType.UNSUPPORTED.value == "unsupported"
