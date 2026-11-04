"""Phase 3 Synthesizer tests.

All tests mock truthguard.llm.complete so no LLM API key is needed.
The key invariants tested:
  - claims always cite retrieved clauses
  - numbers in claims must appear in cited passages
  - conflicting passages produce separate claims, never blended values
  - bad claims after retry become UNSUPPORTED findings
  - small model is chosen when family has 1 clause + no conflicts
"""
from __future__ import annotations

import os
from datetime import date
from unittest.mock import patch

os.environ.setdefault("BASELINE_SYNTHESIZE", "false")

from truthguard.contracts import (
    Clause,
    FindingType,
    RetrievalResult,
    RetrievedClause,
    TGState,
    User,
)
from truthguard.synthesize.impl import _choose_model, _validate_claim
from truthguard.synthesize.impl import run as impl_run

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _user() -> User:
    return User(user_id="u1", name="Alice", role="employee", access_levels=["all"])


def _clause(cid: str, text: str, **kwargs) -> Clause:
    return Clause(clause_id=cid, doc_id="D", source_text=text, **kwargs)


def _rc(cid: str, text: str, **kwargs) -> RetrievedClause:
    return RetrievedClause(clause=_clause(cid, text, **kwargs), score=1.0, via="search")


def _retrieval(*rcs: RetrievedClause, restricted: bool = False) -> RetrievalResult:
    return RetrievalResult(
        concept_id="c",
        candidates=list(rcs),
        family=list(rcs),
        restricted_conflict=restricted,
    )


def _state(question: str, retrieval: RetrievalResult) -> TGState:
    return TGState(question=question, user=_user(), retrieval=retrieval)


def _llm_response(**kwargs) -> dict:
    """Build a dict the mocked complete() will return."""
    return {"answer_text": kwargs.get("answer_text", "Answer."), "claims": kwargs.get("claims", [])}


# ---------------------------------------------------------------------------
# _choose_model
# ---------------------------------------------------------------------------

class TestChooseModel:
    def test_small_when_single_clause_no_conflict(self):
        r = _retrieval(_rc("c1", "text"), restricted=False)
        assert _choose_model(r) == "small"

    def test_large_when_multiple_clauses(self):
        r = _retrieval(_rc("c1", "t1"), _rc("c2", "t2"), restricted=False)
        assert _choose_model(r) == "large"

    def test_large_when_restricted_conflict(self):
        r = _retrieval(_rc("c1", "text"), restricted=True)
        assert _choose_model(r) == "large"


# ---------------------------------------------------------------------------
# _validate_claim
# ---------------------------------------------------------------------------

class TestValidateClaim:
    from truthguard.synthesize.impl import _LLMClaim

    def _c(self, cid: str, text: str, clause_ids: list[str]):
        from truthguard.synthesize.impl import _LLMClaim
        return _LLMClaim(claim_id="x", text=text, clause_ids=clause_ids)

    def test_valid_claim(self):
        c = self._c("c1", "Limit is 3000 rupees.", ["DOC#1"])
        clauses = {"DOC#1": _clause("DOC#1", "Limit is Rs. 3,000 per transaction.")}
        assert _validate_claim(c, {"DOC#1"}, clauses) is None

    def test_empty_clause_ids_rejected(self):
        c = self._c("c1", "Limit is 3000.", [])
        err = _validate_claim(c, set(), {})
        assert err is not None
        assert "empty" in err

    def test_unknown_clause_id_rejected(self):
        c = self._c("c1", "Limit is 3000.", ["UNKNOWN#1"])
        err = _validate_claim(c, {"DOC#1"}, {})
        assert err is not None

    def test_invented_number_rejected(self):
        c = self._c("c1", "Limit is 9999 rupees.", ["DOC#1"])
        # 9999 is NOT in the source text
        clauses = {"DOC#1": _clause("DOC#1", "Limit is Rs. 3,000 per transaction.")}
        err = _validate_claim(c, {"DOC#1"}, clauses)
        assert err is not None
        assert "9999" in err

    def test_not_found_sentinel_always_valid(self):
        from truthguard.synthesize.impl import _LLMClaim
        c = _LLMClaim(claim_id="c1", text="Not found in the documents.", clause_ids=[])
        assert _validate_claim(c, set(), {}) is None

    def test_hindi_number_matches_english_passage(self):
        """₹3,000 in passage should match '3000' in claim (normalised comparison)."""
        c = self._c("c1", "Limit is 3000.", ["DOC#1"])
        clauses = {"DOC#1": _clause("DOC#1", "Limit is ₹3,000 per transaction.")}
        assert _validate_claim(c, {"DOC#1"}, clauses) is None


# ---------------------------------------------------------------------------
# Full run() tests (with mocked LLM)
# ---------------------------------------------------------------------------

CLAUSE_A = _rc("DOC#1", "Manager approval limit is Rs. 3,000 per transaction.")
CLAUSE_B = _rc("DOC#2", "Manager approval limit is Rs. 5,000 per transaction.")


class TestRun:
    def _mock(self, response: dict):
        """Return a patch context that makes llm.complete return response."""
        return patch("truthguard.llm.complete", return_value=response)

    def test_good_claim_accepted(self):
        r = _retrieval(CLAUSE_A)
        state = _state("What is the manager limit?", r)
        resp = _llm_response(
            answer_text="The limit is Rs. 3,000.",
            claims=[{"claim_id": "c1", "text": "The limit is Rs. 3,000.", "clause_ids": ["DOC#1"]}],
        )
        with self._mock(resp):
            impl_run(state)
        assert len(state.draft.claims) == 1
        assert state.draft.claims[0].clause_ids == ["DOC#1"]
        assert not state.findings

    def test_no_retrieval_returns_not_found(self):
        state = TGState(
            question="anything",
            user=_user(),
            retrieval=RetrievalResult(concept_id=None, candidates=[], family=[]),
        )
        impl_run(state)
        assert "not found" in state.draft.answer_text.lower()
        assert state.draft.claims == []

    def test_invented_number_dropped_as_unsupported(self):
        r = _retrieval(CLAUSE_A)
        state = _state("manager limit?", r)
        # First call: claim with invented 9999
        bad_resp = _llm_response(
            answer_text="Limit is 9999.",
            claims=[{"claim_id": "c1", "text": "Limit is 9999.", "clause_ids": ["DOC#1"]}],
        )
        # Retry: still bad
        with patch("truthguard.llm.complete", return_value=bad_resp):
            impl_run(state)
        # Claim dropped → UNSUPPORTED finding
        assert any(f.type == FindingType.UNSUPPORTED for f in state.findings)

    def test_invalid_citation_dropped(self):
        r = _retrieval(CLAUSE_A)
        state = _state("manager limit?", r)
        resp = _llm_response(
            answer_text="See clause.",
            claims=[{"claim_id": "c1", "text": "Some fact.", "clause_ids": ["NONEXISTENT#9"]}],
        )
        with self._mock(resp):
            impl_run(state)
        assert any(f.type == FindingType.UNSUPPORTED for f in state.findings)

    def test_conflicting_passages_not_blended(self):
        """When two passages disagree, the draft must cite each separately, never average."""
        r = _retrieval(CLAUSE_A, CLAUSE_B)
        state = _state("What is the manager limit?", r)
        # LLM correctly writes two separate claims
        resp = _llm_response(
            answer_text="Limits differ: Rs. 3,000 (DOC#1) and Rs. 5,000 (DOC#2).",
            claims=[
                {"claim_id": "c1", "text": "Manager limit is Rs. 3,000.", "clause_ids": ["DOC#1"]},
                {"claim_id": "c2", "text": "Manager limit is Rs. 5,000.", "clause_ids": ["DOC#2"]},
            ],
        )
        with self._mock(resp):
            impl_run(state)
        # Both claims present, no blending
        assert len(state.draft.claims) == 2
        values = {c.text for c in state.draft.claims}
        assert any("3,000" in v or "3000" in v for v in values)
        assert any("5,000" in v or "5000" in v for v in values)
        # Blended value (4000) must NOT appear
        assert not any("4,000" in v or "4000" in v for v in values)

    def test_blended_value_in_claim_rejected(self):
        """A claim that invents a blended value (not in any passage) is dropped."""
        r = _retrieval(CLAUSE_A, CLAUSE_B)
        state = _state("manager limit?", r)
        # LLM incorrectly blends: 4000 is not in either passage
        blended_resp = _llm_response(
            answer_text="Average is 4000.",
            claims=[{"claim_id": "c1", "text": "Limit is 4000.", "clause_ids": ["DOC#1", "DOC#2"]}],
        )
        with patch("truthguard.llm.complete", return_value=blended_resp):
            impl_run(state)
        assert any(f.type == FindingType.UNSUPPORTED for f in state.findings)

    def test_retry_on_bad_claim(self):
        """First call has an invalid claim; retry produces a valid one."""
        r = _retrieval(CLAUSE_A)
        state = _state("manager limit?", r)
        bad = _llm_response(
            answer_text="Invented.",
            claims=[{"claim_id": "c1", "text": "Limit is 9999.", "clause_ids": ["DOC#1"]}],
        )
        good = _llm_response(
            answer_text="The limit is Rs. 3,000.",
            claims=[{"claim_id": "c1", "text": "Limit is Rs. 3,000.", "clause_ids": ["DOC#1"]}],
        )
        call_count = 0

        def mock_complete(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return bad if call_count == 1 else good

        with patch("truthguard.llm.complete", side_effect=mock_complete):
            impl_run(state)

        assert call_count == 2
        assert len(state.draft.claims) == 1
        assert not state.findings

    def test_model_routing_small(self):
        """Single-clause + no conflict → small model is passed to llm.complete."""
        r = _retrieval(CLAUSE_A, restricted=False)
        state = _state("manager limit?", r)
        resp = _llm_response(
            answer_text="Limit is Rs. 3,000.",
            claims=[{"claim_id": "c1", "text": "Limit is Rs. 3,000.", "clause_ids": ["DOC#1"]}],
        )
        captured = {}

        def mock_complete(prompt_name, variables, model="small", **kwargs):
            captured["model"] = model
            return resp

        with patch("truthguard.llm.complete", side_effect=mock_complete):
            impl_run(state)

        assert captured["model"] == "small"

    def test_model_routing_large(self):
        """Multi-clause family → large model."""
        r = _retrieval(CLAUSE_A, CLAUSE_B, restricted=False)
        state = _state("manager limit?", r)
        resp = _llm_response(
            answer_text="Limits vary.",
            claims=[
                {"claim_id": "c1", "text": "Rs. 3,000.", "clause_ids": ["DOC#1"]},
                {"claim_id": "c2", "text": "Rs. 5,000.", "clause_ids": ["DOC#2"]},
            ],
        )
        captured = {}

        def mock_complete(prompt_name, variables, model="small", **kwargs):
            captured["model"] = model
            return resp

        with patch("truthguard.llm.complete", side_effect=mock_complete):
            impl_run(state)

        assert captured["model"] == "large"

    def test_hindi_question_language_passed(self):
        """question_language is forwarded to the LLM variables."""
        r = _retrieval(CLAUSE_A)
        state = _state("सीमा क्या है?", r)
        state.question_language = "hi"
        resp = _llm_response(
            answer_text="सीमा Rs. 3,000 है।",
            claims=[{"claim_id": "c1", "text": "सीमा Rs. 3,000 है।", "clause_ids": ["DOC#1"]}],
        )
        captured = {}

        def mock_complete(prompt_name, variables, **kwargs):
            captured["vars"] = variables
            return resp

        with patch("truthguard.llm.complete", side_effect=mock_complete):
            impl_run(state)

        assert captured["vars"]["question_language"] == "hi"
        assert captured["vars"]["language_name"] == "Hindi"

    def test_as_of_instruction_included(self):
        r = _retrieval(CLAUSE_A)
        state = _state("manager limit?", r)
        state.as_of = date(2024, 1, 1)
        resp = _llm_response(
            answer_text="Limit is Rs. 3,000.",
            claims=[{"claim_id": "c1", "text": "Limit is Rs. 3,000.", "clause_ids": ["DOC#1"]}],
        )
        captured = {}

        def mock_complete(prompt_name, variables, **kwargs):
            captured["vars"] = variables
            return resp

        with patch("truthguard.llm.complete", side_effect=mock_complete):
            impl_run(state)

        assert "2024-01-01" in captured["vars"]["as_of_instruction"]

    def test_llm_failure_produces_not_found_and_finding(self):
        r = _retrieval(CLAUSE_A)
        state = _state("manager limit?", r)
        with patch("truthguard.llm.complete", side_effect=RuntimeError("timeout")):
            impl_run(state)
        assert "not found" in state.draft.answer_text.lower()
        assert any(f.type == FindingType.UNSUPPORTED for f in state.findings)
