"""Smoke test for Phase 2 baseline."""
from __future__ import annotations

from truthguard.contracts import TGState, User
from truthguard.ingest import run as ingest_run
from truthguard.retrieve import run as retrieve_run


def _employee() -> User:
    return User(user_id="u1", role="employee", access_levels=["all"])


def test_retrieve_returns_result(tmp_txt):
    path = tmp_txt("policy.txt", "Managers may approve expenses up to $5,000 per transaction.")
    ingest_run([path])

    state = TGState(question="What is the manager approval limit?", user=_employee())
    state = retrieve_run(state)

    assert state.retrieval is not None
    assert len(state.retrieval.candidates) >= 1


def test_retrieve_empty_corpus():
    state = TGState(question="What is the limit?", user=_employee())
    state = retrieve_run(state)

    assert state.retrieval is not None
    assert state.retrieval.candidates == []


def test_retrieve_permission_filter(tmp_txt):
    path = tmp_txt("compliance.txt", "Board members receive special compensation.")
    ingest_run([path], access_level="board")

    # employee with access_level=['all'] should not see board-only clauses
    state = TGState(question="Board compensation", user=_employee())
    state = retrieve_run(state)

    for rc in state.retrieval.candidates:
        assert rc.clause.access_level != "board", "Permission leak: employee saw board-only clause"
