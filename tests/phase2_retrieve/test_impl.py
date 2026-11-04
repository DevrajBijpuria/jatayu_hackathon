"""Phase 2 retriever tests.

The permission-leak test is the most critical: it must FAIL if the
_apply_filters() call is removed from impl.run().  Every other test runs
against a fixture DB built with a fixed pair of clauses so no ML models
or LLM key are needed.
"""
from __future__ import annotations

import os
from datetime import date

# Keep LLM and ML models out of these tests
os.environ.setdefault("LLM_API_KEY", "")
os.environ.setdefault("BASELINE_RETRIEVE", "false")  # test the real impl

from truthguard import config
from truthguard.contracts import Clause, RetrievedClause, TGState, User
from truthguard.db.conn import get_conn
from truthguard.retrieve.impl import (
    _apply_filters,
    _expand_family,
    _has_restricted_conflict,
    _pick_concept,
    _rrf,
)
from truthguard.retrieve.impl import (
    run as impl_run,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    title TEXT, source_path TEXT, doc_type TEXT, language TEXT,
    origin TEXT DEFAULT 'upload', origin_ref TEXT, content_hash TEXT,
    issuer TEXT, issued_date DATE, access_level TEXT DEFAULT 'all',
    injection_flag BOOLEAN DEFAULT FALSE, translation_of TEXT,
    ingested_at TIMESTAMP DEFAULT current_timestamp
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
    conflict_id TEXT PRIMARY KEY,
    clause_a TEXT, clause_b TEXT,
    kind TEXT, score DOUBLE,
    detected_at TIMESTAMP DEFAULT current_timestamp
);
"""

_DOC_SQL = "INSERT INTO documents (doc_id, access_level, injection_flag) VALUES (?, ?, FALSE)"
_CLAUSE_SQL = (
    "INSERT INTO clauses (clause_id, doc_id, source_text, concept_id, subject, "
    "access_level, status, effective_date) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)"
)


def _employee() -> User:
    return User(user_id="u1", name="Alice", role="employee", access_levels=["all"])


def _compliance() -> User:
    return User(user_id="u2", name="Bob", role="admin", access_levels=["all", "compliance"])


def _state(question: str, user: User, as_of: date | None = None) -> TGState:
    return TGState(question=question, user=user, as_of=as_of)


def _setup_fixture_db(conn):
    """Insert two documents and three clauses into the in-memory DB."""
    conn.execute(_SCHEMA)
    # Public doc
    conn.execute(_DOC_SQL, ["PUBLIC-DOC", "all"])
    conn.execute(_CLAUSE_SQL, [
        "PUBLIC-DOC#1", "PUBLIC-DOC",
        "Manager approval limit is five thousand rupees per transaction.",
        "approval_limit", "manager", "all", None,
    ])
    # Compliance-only doc
    conn.execute(_DOC_SQL, ["PRIV-DOC", "compliance"])
    conn.execute(_CLAUSE_SQL, [
        "PRIV-DOC#1", "PRIV-DOC",
        "Manager approval limit is twenty thousand rupees for compliance officers.",
        "approval_limit", "manager", "compliance", None,
    ])
    # A second public clause with a different concept
    conn.execute(_CLAUSE_SQL, [
        "PUBLIC-DOC#2", "PUBLIC-DOC",
        "Work from home days are limited to two days per week.",
        "wfh_policy", "employee", "all", None,
    ])


# ---------------------------------------------------------------------------
# Permission-leak test — MOST IMPORTANT
# Must fail if _apply_filters() is removed from impl.run().
# ---------------------------------------------------------------------------

class TestPermissionLeak:
    def test_employee_cannot_see_compliance_clause(self, monkeypatch, tmp_path):
        """PRIV-DOC#1 (compliance-only) must never appear for an employee user."""
        monkeypatch.setattr(config, "INDEX_DIR", str(tmp_path / "no_index"))
        conn = get_conn()
        _setup_fixture_db(conn)

        state = impl_run(_state("What is the manager approval limit?", _employee()))

        all_ids = {rc.clause.clause_id for rc in state.retrieval.candidates}
        all_ids |= {rc.clause.clause_id for rc in state.retrieval.family}
        assert "PRIV-DOC#1" not in all_ids, (
            "Permission leak: compliance-only clause visible to employee user"
        )

    def test_compliance_user_can_see_compliance_clause(self, monkeypatch, tmp_path):
        """Compliance user should see PRIV-DOC#1 (sanity check for the above)."""
        monkeypatch.setattr(config, "INDEX_DIR", str(tmp_path / "no_index"))
        conn = get_conn()
        _setup_fixture_db(conn)

        state = impl_run(_state("What is the manager approval limit?", _compliance()))

        family_ids = {rc.clause.clause_id for rc in state.retrieval.family}
        assert "PRIV-DOC#1" in family_ids

    def test_access_level_filter_is_deterministic(self, monkeypatch, tmp_path):
        """Running twice returns the same filtered set."""
        monkeypatch.setattr(config, "INDEX_DIR", str(tmp_path / "no_index"))
        conn = get_conn()
        _setup_fixture_db(conn)

        s1 = impl_run(_state("manager approval limit", _employee()))
        s2 = impl_run(_state("manager approval limit", _employee()))

        ids1 = {rc.clause.clause_id for rc in s1.retrieval.candidates}
        ids2 = {rc.clause.clause_id for rc in s2.retrieval.candidates}
        assert ids1 == ids2


# ---------------------------------------------------------------------------
# RRF fusion unit tests
# ---------------------------------------------------------------------------

class TestRRF:
    def test_single_list(self):
        scores = _rrf([["a", "b", "c"]])
        assert scores["a"] > scores["b"] > scores["c"]

    def test_two_lists_boost_overlap(self):
        # "b" appears in both lists → higher combined score than "a" (rank 1 in one list only)
        scores = _rrf([["a", "b"], ["b", "c"]])
        assert scores["b"] > scores["a"]

    def test_empty_lists_ignored(self):
        scores = _rrf([[], ["x", "y"]])
        assert scores["x"] > scores["y"]
        assert "x" in scores

    def test_k_parameter(self):
        s60 = _rrf([["a"]], k=60)
        s1 = _rrf([["a"]], k=1)
        # Smaller k → higher score for rank-1 item
        assert s1["a"] > s60["a"]


# ---------------------------------------------------------------------------
# as_of filter tests
# ---------------------------------------------------------------------------

class TestAsOfFilter:
    def test_future_clause_excluded(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "INDEX_DIR", str(tmp_path / "no_index"))
        conn = get_conn()
        conn.execute(_SCHEMA)
        conn.execute(_DOC_SQL, ["DOC-A", "all"])
        # Clause effective 2025-06-01, ask as_of 2024-01-01
        conn.execute(
            "INSERT INTO clauses (clause_id, doc_id, source_text, concept_id, "
            "access_level, status, effective_date) VALUES (?, ?, ?, ?, 'all', 'active', ?)",
            ["DOC-A#1", "DOC-A", "Manager limit is five thousand.", "approval_limit", "2025-06-01"],
        )

        state = impl_run(_state(
            "manager limit",
            _employee(),
            as_of=date(2024, 1, 1),
        ))

        all_ids = {rc.clause.clause_id for rc in state.retrieval.candidates}
        all_ids |= {rc.clause.clause_id for rc in state.retrieval.family}
        assert "DOC-A#1" not in all_ids

    def test_null_date_clause_kept_under_as_of(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "INDEX_DIR", str(tmp_path / "no_index"))
        conn = get_conn()
        conn.execute(_SCHEMA)
        conn.execute(_DOC_SQL, ["DOC-B", "all"])
        conn.execute(
            "INSERT INTO clauses (clause_id, doc_id, source_text, concept_id, "
            "access_level, status, effective_date) VALUES (?, ?, ?, ?, 'all', 'active', ?)",
            ["DOC-B#1", "DOC-B", "Manager limit is five thousand.", "approval_limit", None],
        )

        state = impl_run(_state(
            "manager limit",
            _employee(),
            as_of=date(2020, 1, 1),
        ))

        # Null-date clause must NOT be dropped silently (it stays in family for Phase 4 to flag)
        family_ids = {rc.clause.clause_id for rc in state.retrieval.family}
        assert "DOC-B#1" in family_ids


# ---------------------------------------------------------------------------
# Family expansion tests
# ---------------------------------------------------------------------------

class TestFamilyExpansion:
    def test_amendment_retrieved_via_family(self, monkeypatch, tmp_path):
        """An amendment with low keyword overlap should still appear via family expansion."""
        monkeypatch.setattr(config, "INDEX_DIR", str(tmp_path / "no_index"))
        conn = get_conn()
        conn.execute(_SCHEMA)
        conn.execute(_DOC_SQL, ["POLICY-V1", "all"])
        conn.execute(_DOC_SQL, ["AMEND-V2", "all"])
        conn.execute(_CLAUSE_SQL, [
            "POLICY-V1#1", "POLICY-V1",
            "Staff may claim up to three thousand rupees for meals.",
            "meal_allowance", None, "all", "2020-01-01",
        ])
        # Amendment has very different wording — keyword search would miss it
        conn.execute(_CLAUSE_SQL, [
            "AMEND-V2#1", "AMEND-V2",
            "Circular xyz supersedes earlier limits effective April 2024.",
            "meal_allowance", None, "all", "2024-04-01",
        ])

        state = impl_run(_state("meal claim limit for employees", _employee()))

        family_ids = {rc.clause.clause_id for rc in state.retrieval.family}
        assert "POLICY-V1#1" in family_ids
        assert "AMEND-V2#1" in family_ids, (
            "Amendment should appear via family expansion even if keyword-missed"
        )

    def test_family_expansion_includes_all_concept_clauses(self):
        """_expand_family returns all concept members regardless of keyword match."""
        conn = get_conn()
        conn.execute(_SCHEMA)
        conn.execute(_DOC_SQL, ["DOC-X", "all"])
        conn.execute(_DOC_SQL, ["DOC-Y", "all"])
        conn.execute(_CLAUSE_SQL, [
            "DOC-X#1", "DOC-X",
            "Manager limit is five thousand rupees.",
            "approval_limit", None, "all", None,
        ])
        # DOC-Y#1 has very different wording but same concept_id
        conn.execute(_CLAUSE_SQL, [
            "DOC-Y#1", "DOC-Y",
            "Reference TG-2024 rescinds prior notification.",
            "approval_limit", None, "all", None,
        ])

        clauses = _expand_family(conn, "approval_limit", None, ["all"], None)
        ids = {c.clause_id for c in clauses}
        assert "DOC-X#1" in ids
        assert "DOC-Y#1" in ids


# ---------------------------------------------------------------------------
# Restricted-conflict flag tests
# ---------------------------------------------------------------------------

class TestRestrictedConflict:
    def _insert_conflict(self, conn, cid_a: str, cid_b: str):
        conn.execute(
            "INSERT INTO conflicts (conflict_id, clause_a, clause_b, kind, score) VALUES (?, ?, ?, 'value_mismatch', 1.0)",
            [f"{cid_a}|{cid_b}", cid_a, cid_b],
        )

    def test_restricted_conflict_detected(self):
        """Hidden clause conflicts with visible → restricted_conflict=True."""
        conn = get_conn()
        conn.execute(_SCHEMA)
        conn.execute(_DOC_SQL, ["PUB", "all"])
        conn.execute(_DOC_SQL, ["SEC", "compliance"])
        conn.execute(_CLAUSE_SQL, ["PUB#1", "PUB", "Limit is five thousand.", "approval_limit", None, "all", None])
        conn.execute(_CLAUSE_SQL, ["SEC#1", "SEC", "Limit is twenty thousand.", "approval_limit", None, "compliance", None])
        self._insert_conflict(conn, "PUB#1", "SEC#1")

        result = _has_restricted_conflict(conn, "approval_limit", ["all"])
        assert result is True

    def test_no_restricted_conflict_when_both_visible(self):
        """When user can see both sides, it's a normal conflict, not restricted."""
        conn = get_conn()
        conn.execute(_SCHEMA)
        conn.execute(_DOC_SQL, ["A", "all"])
        conn.execute(_DOC_SQL, ["B", "all"])
        conn.execute(_CLAUSE_SQL, ["A#1", "A", "Limit is five.", "some_concept", None, "all", None])
        conn.execute(_CLAUSE_SQL, ["B#1", "B", "Limit is ten.", "some_concept", None, "all", None])
        self._insert_conflict(conn, "A#1", "B#1")

        result = _has_restricted_conflict(conn, "some_concept", ["all"])
        assert result is False

    def test_restricted_conflict_flag_in_retrieval_result(self, monkeypatch, tmp_path):
        """impl.run() sets restricted_conflict=True when a hidden conflict exists."""
        monkeypatch.setattr(config, "INDEX_DIR", str(tmp_path / "no_index"))
        conn = get_conn()
        _setup_fixture_db(conn)
        # Add conflict between public and private clause
        conn.execute(
            "INSERT INTO conflicts (conflict_id, clause_a, clause_b, kind, score) VALUES (?, ?, ?, 'value_mismatch', 1.0)",
            ["PUBLIC-DOC#1|PRIV-DOC#1", "PUBLIC-DOC#1", "PRIV-DOC#1"],
        )

        state = impl_run(_state("What is the manager approval limit?", _employee()))

        assert state.retrieval.restricted_conflict is True


# ---------------------------------------------------------------------------
# Question language detection
# ---------------------------------------------------------------------------

class TestQuestionLanguage:
    def test_english_question(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "INDEX_DIR", str(tmp_path / "no_index"))
        conn = get_conn()
        _setup_fixture_db(conn)
        state = impl_run(_state("What is the manager approval limit?", _employee()))
        assert state.question_language == "en"

    def test_hindi_question_detected(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "INDEX_DIR", str(tmp_path / "no_index"))
        conn = get_conn()
        _setup_fixture_db(conn)
        # Devanagari question: "manager ki approval limit kya hai?"
        state = impl_run(_state("मैनेजर की अनुमोदन सीमा क्या है?", _employee()))
        assert state.question_language in ("hi", "mixed")


# ---------------------------------------------------------------------------
# Concept selection unit tests
# ---------------------------------------------------------------------------

class TestPickConcept:
    def _rc(self, concept: str | None, score: float = 1.0):
        c = Clause(clause_id="x", doc_id="d", source_text="t", concept_id=concept)
        return RetrievedClause(clause=c, score=score, via="search")

    def test_most_common_wins(self):
        rcs = [self._rc("a"), self._rc("a"), self._rc("b")]
        assert _pick_concept(rcs) == "a"

    def test_tie_resolved_by_score(self):
        rcs = [self._rc("a", 0.9), self._rc("b", 1.5)]
        assert _pick_concept(rcs) == "b"

    def test_all_none(self):
        assert _pick_concept([self._rc(None)]) is None

    def test_empty(self):
        assert _pick_concept([]) is None


# ---------------------------------------------------------------------------
# _apply_filters unit tests (verify the guard works in isolation)
# ---------------------------------------------------------------------------

class TestApplyFilters:
    def _clause(self, cid: str, access: str, eff_date: date | None = None) -> Clause:
        return Clause(
            clause_id=cid, doc_id="d", source_text="t",
            access_level=access, effective_date=eff_date,
        )

    def test_blocks_wrong_access_level(self):
        clauses = {
            "c1": self._clause("c1", "all"),
            "c2": self._clause("c2", "compliance"),
        }
        result = _apply_filters(clauses, ["all"], None)
        assert "c1" in result
        assert "c2" not in result

    def test_blocks_future_clause(self):
        clauses = {
            "c1": self._clause("c1", "all", date(2030, 1, 1)),
        }
        result = _apply_filters(clauses, ["all"], date(2024, 1, 1))
        assert "c1" not in result

    def test_keeps_null_date_under_as_of(self):
        clauses = {"c1": self._clause("c1", "all", None)}
        result = _apply_filters(clauses, ["all"], date(2024, 1, 1))
        assert "c1" in result
