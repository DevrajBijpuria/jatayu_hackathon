"""Phase 4 Critic tests.

All NLI calls are mocked so no ML models or LLM API key are needed.
Covers all five tools in isolation and six integration scenarios:
  - superseded clause → STALE
  - fabricated number → UNSUPPORTED
  - qualitative contradiction → CONTRADICTION
  - scoped value mismatch → CONTRADICTION
  - NULL-date clause → STALE with evidence={'unknown_date': ...}
  - clean case → no findings
  - restricted_conflict flag → CONTRADICTION with clause_ids=[]
"""
from __future__ import annotations

import os
from datetime import date
from unittest.mock import patch

os.environ.setdefault("BASELINE_CRITIC", "false")
os.environ.setdefault("LLM_API_KEY", "")

from truthguard.contracts import (
    Claim,
    Clause,
    Draft,
    FindingType,
    RetrievalResult,
    RetrievedClause,
    TGState,
    User,
)
from truthguard.critic.impl import (
    claim_supported,
    compare_values,
    find_newer,
    lookup_conflicts,
    nli,
)
from truthguard.critic.impl import (
    run as impl_run,
)
from truthguard.db.conn import get_conn

# ---------------------------------------------------------------------------
# Schema + helpers
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY, title TEXT, source_path TEXT, doc_type TEXT,
    language TEXT, origin TEXT DEFAULT 'upload', origin_ref TEXT,
    content_hash TEXT, issuer TEXT, issued_date DATE,
    access_level TEXT DEFAULT 'all', injection_flag BOOLEAN DEFAULT FALSE,
    translation_of TEXT, ingested_at TIMESTAMP DEFAULT current_timestamp
);
CREATE TABLE IF NOT EXISTS clauses (
    clause_id TEXT PRIMARY KEY, doc_id TEXT, section TEXT,
    source_text TEXT NOT NULL, language TEXT, text_en TEXT,
    concept_id TEXT, subject TEXT, clause_type TEXT,
    value_num DOUBLE, value_unit TEXT, value_text TEXT, condition_text TEXT,
    scope TEXT DEFAULT '*', issuer TEXT, authority_rank INTEGER,
    effective_date DATE, supersedes TEXT, supersedes_conf DOUBLE,
    access_level TEXT DEFAULT 'all', extract_conf DOUBLE,
    status TEXT DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id TEXT PRIMARY KEY, clause_a TEXT, clause_b TEXT,
    kind TEXT, score DOUBLE,
    detected_at TIMESTAMP DEFAULT current_timestamp
);
"""

_DOC = "INSERT INTO documents (doc_id, access_level, injection_flag) VALUES (?, 'all', FALSE)"


def _setup():
    conn = get_conn()
    conn.execute(_SCHEMA)
    return conn


def _user(access=None) -> User:
    return User(user_id="u1", name="Test", role="employee", access_levels=access or ["all"])


def _clause(cid: str, text: str, **kw) -> Clause:
    return Clause(clause_id=cid, doc_id="D", source_text=text, **kw)


def _rc(cid: str, text: str, **kw) -> RetrievedClause:
    return RetrievedClause(clause=_clause(cid, text, **kw), score=1.0, via="search")


def _retrieval(*rcs: RetrievedClause, restricted: bool = False) -> RetrievalResult:
    return RetrievalResult(
        concept_id="c",
        candidates=list(rcs),
        family=list(rcs),
        restricted_conflict=restricted,
    )


def _draft(*claims: tuple) -> Draft:
    """claims = [(claim_id, text, [clause_ids]), ...]"""
    return Draft(
        answer_text="answer",
        claims=[Claim(claim_id=c[0], text=c[1], clause_ids=c[2]) for c in claims],
    )


def _state(retrieval: RetrievalResult, draft: Draft | None = None, as_of: date | None = None) -> TGState:
    return TGState(question="test", user=_user(), retrieval=retrieval, draft=draft, as_of=as_of)


def _insert_clause(conn, cid: str, doc_id: str, text: str, **kw) -> None:
    conn.execute(_DOC, [doc_id]) if not conn.execute(
        "SELECT 1 FROM documents WHERE doc_id = ?", [doc_id]
    ).fetchone() else None
    conn.execute(
        """INSERT INTO clauses (clause_id, doc_id, source_text, concept_id, subject,
           clause_type, value_num, scope, effective_date, supersedes, access_level, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
        [
            cid, doc_id, text,
            kw.get("concept_id"), kw.get("subject"),
            kw.get("clause_type"), kw.get("value_num"),
            kw.get("scope", "*"),
            kw.get("effective_date"),
            kw.get("supersedes"),
            kw.get("access_level", "all"),
        ],
    )


# ---------------------------------------------------------------------------
# Tool: compare_values
# ---------------------------------------------------------------------------

class TestCompareValues:
    def test_no_diff_when_values_equal(self):
        conn = _setup()
        _insert_clause(conn, "C1", "D", "text", value_num=3000.0, concept_id="c")
        _insert_clause(conn, "C2", "D", "text", value_num=3000.0, concept_id="c")
        assert compare_values(conn, ["C1", "C2"]) == []

    def test_detects_value_num_diff(self):
        conn = _setup()
        _insert_clause(conn, "C1", "D", "text", value_num=3000.0)
        _insert_clause(conn, "C2", "D", "text", value_num=5000.0)
        diffs = compare_values(conn, ["C1", "C2"])
        assert any(d["field"] == "value_num" for d in diffs)

    def test_detects_scope_diff(self):
        conn = _setup()
        _insert_clause(conn, "C1", "D", "text", scope="*")
        _insert_clause(conn, "C2", "D", "text", scope="location=mumbai")
        diffs = compare_values(conn, ["C1", "C2"])
        assert any(d["field"] == "scope" for d in diffs)

    def test_ignores_null_value_num(self):
        conn = _setup()
        _insert_clause(conn, "C1", "D", "text", value_num=None)
        _insert_clause(conn, "C2", "D", "text", value_num=5000.0)
        diffs = compare_values(conn, ["C1", "C2"])
        assert not any(d["field"] == "value_num" for d in diffs)

    def test_empty_when_fewer_than_two(self):
        conn = _setup()
        _insert_clause(conn, "C1", "D", "text")
        assert compare_values(conn, ["C1"]) == []


# ---------------------------------------------------------------------------
# Tool: nli (graceful fallback when model absent)
# ---------------------------------------------------------------------------

class TestNli:
    def test_returns_expected_keys(self):
        result = nli("text a", "text b")
        # Either real model output or graceful fallback
        assert isinstance(result, dict)
        # Must contain at least some keys
        assert len(result) > 0

    def test_fallback_on_missing_model(self):
        """If the NLI model raises, we get a neutral fallback."""
        with patch("truthguard.critic.impl._get_nli", side_effect=RuntimeError("no model")):
            result = nli("hello", "world")
        assert result == {"contradiction": 0.0, "entailment": 0.0, "neutral": 1.0}


# ---------------------------------------------------------------------------
# Tool: lookup_conflicts
# ---------------------------------------------------------------------------

class TestLookupConflicts:
    def test_returns_conflicts_for_clause(self):
        conn = _setup()
        _insert_clause(conn, "C1", "D1", "text a")
        _insert_clause(conn, "C2", "D1", "text b")
        conn.execute(
            "INSERT INTO conflicts (conflict_id, clause_a, clause_b, kind, score) VALUES (?, ?, ?, ?, ?)",
            ["CF1", "C1", "C2", "value_mismatch", 1.0],
        )
        result = lookup_conflicts(conn, "C1")
        assert len(result) == 1
        assert result[0]["clause_a"] == "C1"
        assert result[0]["kind"] == "value_mismatch"

    def test_returns_conflicts_when_clause_b(self):
        conn = _setup()
        _insert_clause(conn, "C1", "D1", "text a")
        _insert_clause(conn, "C2", "D1", "text b")
        conn.execute(
            "INSERT INTO conflicts (conflict_id, clause_a, clause_b, kind, score) VALUES (?, ?, ?, ?, ?)",
            ["CF1", "C1", "C2", "nli_contradiction", 0.9],
        )
        result = lookup_conflicts(conn, "C2")
        assert len(result) == 1

    def test_empty_when_no_conflicts(self):
        conn = _setup()
        _insert_clause(conn, "C1", "D1", "text")
        assert lookup_conflicts(conn, "C1") == []


# ---------------------------------------------------------------------------
# Tool: find_newer
# ---------------------------------------------------------------------------

class TestFindNewer:
    def test_finds_explicit_supersession(self):
        conn = _setup()
        _insert_clause(conn, "P1", "D", "old policy", concept_id="c",
                       effective_date=date(2023, 1, 1))
        _insert_clause(conn, "A1", "D", "amendment", concept_id="c",
                       effective_date=date(2024, 1, 1), supersedes="P1")
        result = find_newer(conn, "P1", ["all"], None)
        assert any(r["clause_id"] == "A1" for r in result)

    def test_finds_newer_same_concept(self):
        conn = _setup()
        _insert_clause(conn, "P1", "D", "old limit Rs 3000", concept_id="c",
                       subject="manager", scope="*", effective_date=date(2023, 1, 1))
        _insert_clause(conn, "P2", "D", "new limit Rs 5000", concept_id="c",
                       subject="manager", scope="*", effective_date=date(2024, 6, 1))
        result = find_newer(conn, "P1", ["all"], None)
        assert any(r["clause_id"] == "P2" for r in result)

    def test_respects_access_level(self):
        conn = _setup()
        _insert_clause(conn, "P1", "D", "public", concept_id="c",
                       effective_date=date(2023, 1, 1))
        _insert_clause(conn, "A1", "D", "restricted amendment", concept_id="c",
                       effective_date=date(2024, 1, 1), supersedes="P1",
                       access_level="compliance")
        result = find_newer(conn, "P1", ["all"], None)
        assert not any(r["clause_id"] == "A1" for r in result)

    def test_respects_as_of(self):
        conn = _setup()
        _insert_clause(conn, "P1", "D", "old", concept_id="c",
                       effective_date=date(2023, 1, 1))
        _insert_clause(conn, "A1", "D", "new", concept_id="c",
                       effective_date=date(2025, 1, 1), supersedes="P1")
        # as_of before A1's date → should not appear
        result = find_newer(conn, "P1", ["all"], date(2024, 6, 1))
        assert not any(r["clause_id"] == "A1" for r in result)

    def test_returns_empty_when_no_newer(self):
        conn = _setup()
        _insert_clause(conn, "P1", "D", "only clause", concept_id="c",
                       effective_date=date(2024, 1, 1))
        assert find_newer(conn, "P1", ["all"], None) == []


# ---------------------------------------------------------------------------
# Tool: claim_supported
# ---------------------------------------------------------------------------

class TestClaimSupported:
    def _mock_nli_entail(self):
        return patch("truthguard.critic.impl.nli", return_value={"entailment": 0.9, "contradiction": 0.05, "neutral": 0.05})

    def _mock_nli_low(self):
        return patch("truthguard.critic.impl.nli", return_value={"entailment": 0.2, "contradiction": 0.7, "neutral": 0.1})

    def test_supported_claim(self):
        conn = _setup()
        _insert_clause(conn, "C1", "D", "Limit is Rs. 3,000 per transaction.")
        with self._mock_nli_entail():
            result = claim_supported("Limit is Rs. 3,000.", "C1", conn)
        assert result["entailment"] >= 0.5
        assert result["number_present"] is True

    def test_unsupported_low_entailment(self):
        conn = _setup()
        _insert_clause(conn, "C1", "D", "Pre-approval is required for all expenses.")
        with self._mock_nli_low():
            result = claim_supported("No approval needed.", "C1", conn)
        assert result["entailment"] < 0.5

    def test_fabricated_number_not_present(self):
        conn = _setup()
        _insert_clause(conn, "C1", "D", "Limit is Rs. 3,000 per transaction.")
        with self._mock_nli_entail():
            result = claim_supported("Limit is 9999.", "C1", conn)
        assert result["number_present"] is False

    def test_missing_clause_returns_unsupported(self):
        conn = _setup()
        result = claim_supported("any claim", "NONEXISTENT#1", conn)
        assert result["entailment"] == 0.0
        assert result["number_present"] is False


# ---------------------------------------------------------------------------
# Integration: run() — six scenarios
# ---------------------------------------------------------------------------

_NLI_ENTAIL = {"entailment": 0.9, "contradiction": 0.05, "neutral": 0.05}
_NLI_NEUTRAL = {"entailment": 0.0, "contradiction": 0.0, "neutral": 1.0}
_NLI_CONTRA = {"entailment": 0.0, "contradiction": 0.95, "neutral": 0.05}


class TestRunSupersededClause:
    """Draft cites Policy v1 when Amendment v2 exists → STALE finding."""

    def test_superseded_clause_produces_stale(self):
        conn = _setup()
        _insert_clause(conn, "P1#1", "D1", "Limit is Rs. 3,000.",
                       concept_id="limit", effective_date=date(2023, 1, 1))
        _insert_clause(conn, "A1#1", "D1", "Limit is Rs. 5,000.",
                       concept_id="limit", effective_date=date(2024, 1, 1), supersedes="P1#1")

        rc_p1 = _rc("P1#1", "Limit is Rs. 3,000.", concept_id="limit",
                    effective_date=date(2023, 1, 1))
        rc_a1 = _rc("A1#1", "Limit is Rs. 5,000.", concept_id="limit",
                    effective_date=date(2024, 1, 1), supersedes="P1#1")
        retrieval = _retrieval(rc_p1, rc_a1)
        draft = _draft(("c1", "Limit is Rs. 3,000.", ["P1#1"]))
        state = _state(retrieval, draft)

        with patch("truthguard.critic.impl.nli", return_value=_NLI_ENTAIL):
            impl_run(state)

        stale = [f for f in state.findings if f.type == FindingType.STALE]
        assert stale, "Expected at least one STALE finding"
        assert any("P1#1" in f.clause_ids for f in stale)


class TestRunFabricatedNumber:
    """Draft claim contains a number not in the cited passage → UNSUPPORTED."""

    def test_fabricated_number_produces_unsupported(self):
        conn = _setup()
        _insert_clause(conn, "P1#1", "D1", "Limit is Rs. 3,000 per transaction.")

        rc = _rc("P1#1", "Limit is Rs. 3,000 per transaction.")
        retrieval = _retrieval(rc)
        draft = _draft(("c1", "Limit is 9999.", ["P1#1"]))
        state = _state(retrieval, draft)

        # NLI entails (high entailment), but number 9999 is not in passage
        with patch("truthguard.critic.impl.nli", return_value=_NLI_ENTAIL):
            impl_run(state)

        unsupported = [f for f in state.findings if f.type == FindingType.UNSUPPORTED]
        assert unsupported, "Expected UNSUPPORTED finding for fabricated number"
        assert any("P1#1" in f.clause_ids for f in unsupported)


class TestRunQualitativeContradiction:
    """Two qualitative clauses that contradict each other → CONTRADICTION finding."""

    def test_qualitative_contradiction(self):
        conn = _setup()
        _insert_clause(conn, "Q1#1", "D1", "Pre-approval is required for all expenses.",
                       clause_type="qualitative", concept_id="approval_policy")
        _insert_clause(conn, "Q2#1", "D2", "No pre-approval is required for expenses.",
                       clause_type="qualitative", concept_id="approval_policy")

        rc1 = _rc("Q1#1", "Pre-approval is required for all expenses.",
                  clause_type="qualitative", concept_id="approval_policy")
        rc2 = _rc("Q2#1", "No pre-approval is required for expenses.",
                  clause_type="qualitative", concept_id="approval_policy")
        retrieval = _retrieval(rc1, rc2)
        draft = _draft(
            ("c1", "Pre-approval required.", ["Q1#1"]),
            ("c2", "No pre-approval required.", ["Q2#1"]),
        )
        state = _state(retrieval, draft)

        # NLI returns contradiction for the qualitative pair
        with patch("truthguard.critic.impl.nli", return_value=_NLI_CONTRA):
            impl_run(state)

        contradictions = [f for f in state.findings if f.type == FindingType.CONTRADICTION]
        assert contradictions, "Expected CONTRADICTION finding"
        nli_findings = [f for f in contradictions if "nli_contradiction" in f.evidence]
        assert nli_findings


class TestRunScopedException:
    """Two clauses with same concept but different value_num → CONTRADICTION (Phase 5 handles scope)."""

    def test_scoped_exception_produces_contradiction(self):
        conn = _setup()
        _insert_clause(conn, "P1#1", "D1", "Limit is Rs. 3,000.",
                       concept_id="limit", value_num=3000.0, scope="*")
        _insert_clause(conn, "P2#1", "D2", "Limit is Rs. 5,000 for Mumbai.",
                       concept_id="limit", value_num=5000.0, scope="location=mumbai")

        rc1 = _rc("P1#1", "Limit is Rs. 3,000.",
                  concept_id="limit", value_num=3000.0, scope="*")
        rc2 = _rc("P2#1", "Limit is Rs. 5,000 for Mumbai.",
                  concept_id="limit", value_num=5000.0, scope="location=mumbai")
        retrieval = _retrieval(rc1, rc2)
        draft = _draft(
            ("c1", "Limit is Rs. 3,000.", ["P1#1"]),
            ("c2", "Limit is Rs. 5,000.", ["P2#1"]),
        )
        state = _state(retrieval, draft)

        with patch("truthguard.critic.impl.nli", return_value=_NLI_ENTAIL):
            impl_run(state)

        contradictions = [f for f in state.findings if f.type == FindingType.CONTRADICTION]
        assert contradictions, "Expected CONTRADICTION for scoped value mismatch"


class TestRunNullDateClause:
    """Cited clause has NULL effective_date, another family member has a date → STALE with unknown_date."""

    def test_null_date_produces_stale_with_evidence(self):
        conn = _setup()
        _insert_clause(conn, "NULL_1", "D1", "Some policy with no date.",
                       concept_id="c", effective_date=None)
        _insert_clause(conn, "DATED_1", "D1", "Same policy with date.",
                       concept_id="c", effective_date=date(2024, 1, 1))

        rc_null = _rc("NULL_1", "Some policy with no date.", concept_id="c", effective_date=None)
        rc_dated = _rc("DATED_1", "Same policy with date.", concept_id="c",
                       effective_date=date(2024, 1, 1))
        retrieval = _retrieval(rc_null, rc_dated)
        draft = _draft(("c1", "Some policy.", ["NULL_1"]))
        state = _state(retrieval, draft)

        with patch("truthguard.critic.impl.nli", return_value=_NLI_ENTAIL):
            impl_run(state)

        stale = [f for f in state.findings if f.type == FindingType.STALE]
        assert stale, "Expected STALE finding for null-date clause"
        # Must have unknown_date evidence
        unknown_findings = [f for f in stale if f.evidence.get("unknown_date") == "NULL_1"]
        assert unknown_findings, "Expected STALE with evidence={'unknown_date': 'NULL_1'}"


class TestRunCleanCase:
    """Single clause, claim well-supported, no conflicts → no findings."""

    def test_clean_case_produces_no_findings(self):
        conn = _setup()
        _insert_clause(conn, "C1#1", "D1", "Manager approval limit is Rs. 3,000.",
                       concept_id="limit", value_num=3000.0, effective_date=date(2024, 1, 1))

        rc = _rc("C1#1", "Manager approval limit is Rs. 3,000.",
                 concept_id="limit", value_num=3000.0, effective_date=date(2024, 1, 1))
        retrieval = _retrieval(rc, restricted=False)
        draft = _draft(("c1", "Manager approval limit is Rs. 3,000.", ["C1#1"]))
        state = _state(retrieval, draft)

        # NLI returns high entailment → supported
        with patch("truthguard.critic.impl.nli", return_value=_NLI_ENTAIL):
            impl_run(state)

        assert state.findings == [], f"Expected no findings, got: {state.findings}"


class TestRunRestrictedConflict:
    """restricted_conflict flag → CONTRADICTION with clause_ids=[] and no hidden text."""

    def test_restricted_conflict_no_hidden_text(self):
        rc = _rc("C1#1", "Public clause text.")
        retrieval = _retrieval(rc, restricted=True)
        draft = _draft(("c1", "Public clause text.", ["C1#1"]))
        state = _state(retrieval, draft)

        conn = _setup()
        _insert_clause(conn, "C1#1", "D1", "Public clause text.", concept_id="c",
                       effective_date=date(2024, 1, 1))

        with patch("truthguard.critic.impl.nli", return_value=_NLI_ENTAIL):
            impl_run(state)

        restricted = [
            f for f in state.findings
            if f.type == FindingType.CONTRADICTION and f.clause_ids == []
        ]
        assert restricted, "Expected CONTRADICTION with clause_ids=[] for restricted conflict"
        assert all(f.detail == "restricted source conflicts" for f in restricted)
        # Confirm no restricted clause text leaked into any finding detail
        for f in state.findings:
            assert "hidden" not in f.detail.lower()
