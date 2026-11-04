"""Phase 5 Resolver tests.

Covers every branch of decide(), scope step, multi-clause groups,
restricted-conflict message, final-text value check, and end-to-end
for all four demo questions from AGENTS.md §8.3 including the
remote-work review-loop round trip.
"""
from __future__ import annotations

import os
from datetime import date

os.environ.setdefault("BASELINE_RESOLVE", "false")

import duckdb

from truthguard.contracts import (
    Claim,
    Clause,
    Decision,
    Draft,
    Finding,
    FindingType,
    RetrievalResult,
    RetrievedClause,
    Status,
    TGState,
    User,
)
from truthguard.db import conn as db_conn
from truthguard.resolve.impl import (
    _apply_scope_step,
    _build_answer_text,
    _extract_missing_fields,
    decide,
    specificity,
)
from truthguard.resolve.impl import (
    run as impl_run,
)

# ---------------------------------------------------------------------------
# DB setup helpers
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY, title TEXT, source_path TEXT, doc_type TEXT,
  language TEXT, origin TEXT DEFAULT 'upload', origin_ref TEXT,
  content_hash TEXT, issuer TEXT, issued_date DATE, access_level TEXT DEFAULT 'all',
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
  conflict_id TEXT PRIMARY KEY, clause_a TEXT, clause_b TEXT,
  kind TEXT, score DOUBLE, detected_at TIMESTAMP DEFAULT current_timestamp
);
CREATE TABLE IF NOT EXISTS review_queue (
  item_id TEXT PRIMARY KEY, clause_id TEXT, reason TEXT, missing_fields TEXT,
  created_at TIMESTAMP DEFAULT current_timestamp, resolved_at TIMESTAMP, resolved_by TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
  log_id TEXT PRIMARY KEY, asked_at TIMESTAMP DEFAULT current_timestamp,
  user_id TEXT, question TEXT, as_of DATE, status TEXT, answer TEXT, trace_json TEXT
);
"""


def _setup() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute(_SCHEMA)
    db_conn._conn = c  # type: ignore[attr-defined]
    return c


def _insert_doc(conn, doc_id: str = "D") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO documents (doc_id, title) VALUES (?, ?)",
        [doc_id, doc_id],
    )


def _insert_clause(conn, cid: str, doc_id: str, text: str, **kw) -> None:
    _insert_doc(conn, doc_id)
    conn.execute(
        """INSERT INTO clauses
           (clause_id, doc_id, source_text, concept_id, subject, value_num,
            value_text, scope, issuer, authority_rank, effective_date, supersedes,
            access_level, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            cid, doc_id, text,
            kw.get("concept_id"), kw.get("subject"),
            kw.get("value_num"), kw.get("value_text"),
            kw.get("scope", "*"), kw.get("issuer"),
            kw.get("authority_rank"), kw.get("effective_date"),
            kw.get("supersedes"),
            kw.get("access_level", "all"), kw.get("status", "active"),
        ],
    )


def _user(role: str = "employee") -> User:
    return User(user_id=f"u-{role}", name=role.title(), role=role, access_levels=["all"])


def _clause(cid: str, text: str, **kw) -> Clause:
    return Clause(clause_id=cid, doc_id="D", source_text=text, **kw)


def _rc(c: Clause, score: float = 1.0) -> RetrievedClause:
    return RetrievedClause(clause=c, score=score, via="search")


def _retrieval(*clauses: Clause, q_scope: str = "*", restricted: bool = False) -> RetrievalResult:
    rcs = [_rc(c) for c in clauses]
    return RetrievalResult(concept_id="c", question_scope=q_scope, candidates=rcs, family=rcs, restricted_conflict=restricted)


def _draft(text: str, *clause_ids: str) -> Draft:
    claims = [Claim(claim_id=f"cl{i}", text=text, clause_ids=[cid]) for i, cid in enumerate(clause_ids)]
    return Draft(answer_text=text, claims=claims)


def _finding(*clause_ids: str, kind: FindingType = FindingType.CONTRADICTION) -> Finding:
    return Finding(type=kind, claim_id=None, clause_ids=list(clause_ids), detail="test", evidence={})


def _state(
    question: str,
    retrieval: RetrievalResult,
    draft: Draft | None = None,
    findings: list[Finding] | None = None,
    as_of: date | None = None,
) -> TGState:
    return TGState(
        question=question,
        user=_user(),
        retrieval=retrieval,
        draft=draft,
        findings=findings or [],
        as_of=as_of,
    )


# ---------------------------------------------------------------------------
# TestDecide — every branch
# ---------------------------------------------------------------------------

class TestDecide:
    _D1 = date(2023, 1, 1)
    _D2 = date(2024, 1, 1)

    def _c(self, cid: str, **kw) -> Clause:
        return _clause(cid, "text", **kw)

    # Rule 2: supersession
    def test_a_supersedes_b(self):
        a = self._c("A", supersedes="B", authority_rank=1, effective_date=self._D2)
        b = self._c("B", authority_rank=1, effective_date=self._D1)
        d = decide(a, b, None)
        assert d.winner == "A"
        assert d.rule == "supersedes"

    def test_b_supersedes_a(self):
        a = self._c("A", authority_rank=1, effective_date=self._D1)
        b = self._c("B", supersedes="A", authority_rank=1, effective_date=self._D2)
        d = decide(a, b, None)
        assert d.winner == "B"
        assert d.rule == "supersedes"

    # Rule 4: authority_rank missing
    def test_a_authority_rank_none(self):
        a = self._c("A", authority_rank=None)
        b = self._c("B", authority_rank=2)
        d = decide(a, b, None)
        assert d.winner is None
        assert d.rule == "abstain_missing"
        assert "A has no authority_rank" in d.explanation

    def test_b_authority_rank_none(self):
        a = self._c("A", authority_rank=2)
        b = self._c("B", authority_rank=None)
        d = decide(a, b, None)
        assert d.winner is None
        assert d.rule == "abstain_missing"
        assert "B has no authority_rank" in d.explanation

    def test_both_authority_rank_none(self):
        a = self._c("A", authority_rank=None)
        b = self._c("B", authority_rank=None)
        d = decide(a, b, None)
        assert d.winner is None
        assert d.rule == "abstain_missing"

    # Rule 3a: authority
    def test_higher_authority_wins(self):
        a = self._c("A", authority_rank=3, effective_date=self._D1, scope="*")
        b = self._c("B", authority_rank=1, effective_date=self._D1, scope="*")
        d = decide(a, b, None)
        assert d.winner == "A"
        assert d.rule == "authority"

    # Rule 3b: specificity
    def test_more_specific_wins(self):
        a = self._c("A", authority_rank=1, effective_date=self._D1, scope="location=mumbai")
        b = self._c("B", authority_rank=1, effective_date=self._D1, scope="*")
        d = decide(a, b, None)
        assert d.winner == "A"
        assert d.rule == "specificity"

    # Rule 4: effective_date missing
    def test_a_effective_date_none(self):
        a = self._c("A", authority_rank=1, effective_date=None)
        b = self._c("B", authority_rank=1, effective_date=self._D1)
        d = decide(a, b, None)
        assert d.winner is None
        assert d.rule == "abstain_missing"
        assert "A has no effective_date" in d.explanation

    def test_b_effective_date_none(self):
        a = self._c("A", authority_rank=1, effective_date=self._D1)
        b = self._c("B", authority_rank=1, effective_date=None)
        d = decide(a, b, None)
        assert d.winner is None
        assert d.rule == "abstain_missing"
        assert "B has no effective_date" in d.explanation

    # Rule 3c: in_force
    def test_in_force_wins_over_future(self):
        past = date(2020, 1, 1)
        future = date(2030, 1, 1)
        ref = date(2024, 6, 1)
        a = self._c("A", authority_rank=1, effective_date=past)
        b = self._c("B", authority_rank=1, effective_date=future)
        d = decide(a, b, ref)
        assert d.winner == "A"
        assert d.rule == "recency"

    # Rule 3c: more recent date wins
    def test_more_recent_date_wins(self):
        a = self._c("A", authority_rank=1, effective_date=self._D2)
        b = self._c("B", authority_rank=1, effective_date=self._D1)
        d = decide(a, b, None)
        assert d.winner == "A"
        assert d.rule == "recency"

    # Rule 4: tie
    def test_equal_everything_abstains(self):
        a = self._c("A", authority_rank=1, effective_date=self._D1)
        b = self._c("B", authority_rank=1, effective_date=self._D1)
        d = decide(a, b, None)
        assert d.winner is None
        assert d.rule == "abstain_tie"


# ---------------------------------------------------------------------------
# TestSpecificity
# ---------------------------------------------------------------------------

class TestSpecificity:
    def test_star_is_zero(self):
        assert specificity(_clause("x", "t", scope="*")) == 0

    def test_one_tag(self):
        assert specificity(_clause("x", "t", scope="location=mumbai")) == 1

    def test_two_tags(self):
        assert specificity(_clause("x", "t", scope="location=mumbai;category=travel")) == 2


# ---------------------------------------------------------------------------
# TestScopeStep
# ---------------------------------------------------------------------------

class TestScopeStep:
    def _c(self, cid: str, scope: str) -> Clause:
        return _clause(cid, "text", authority_rank=1, effective_date=date(2023, 1, 1), scope=scope)

    def test_no_q_scope_resolves_by_scope(self):
        # Per spec: no q_scope + different clause scopes → RESOLVED_BY_SCOPE
        a, b = self._c("A", "*"), self._c("B", "location=mumbai")
        kept, rbs = _apply_scope_step([a, b], "*")
        assert len(kept) == 2
        assert rbs  # spec: different scopes → RESOLVED_BY_SCOPE

    def test_resolved_by_scope_when_different_scopes(self):
        a = self._c("A", "*")
        b = self._c("B", "location=mumbai")
        kept, rbs = _apply_scope_step([a, b], "*")
        assert rbs
        assert len(kept) == 2

    def test_q_scope_drops_incompatible(self):
        a = self._c("A", "*")
        b = self._c("B", "location=delhi")
        # Question is about Mumbai
        kept, rbs = _apply_scope_step([a, b], "location=mumbai")
        assert len(kept) == 1
        assert kept[0].clause_id == "A"
        assert not rbs

    def test_q_scope_keeps_matching(self):
        a = self._c("A", "*")
        b = self._c("B", "location=mumbai")
        kept, rbs = _apply_scope_step([a, b], "location=mumbai")
        assert len(kept) == 2
        assert not rbs


# ---------------------------------------------------------------------------
# TestDecideGroup (multi-clause)
# ---------------------------------------------------------------------------

class TestDecideGroup:
    from truthguard.resolve.impl import _decide_group

    def _c(self, cid: str, rank: int, dt: date, supersedes: str | None = None) -> Clause:
        return _clause(cid, "text", authority_rank=rank, effective_date=dt, supersedes=supersedes)

    def test_single_clause_wins(self):
        from truthguard.resolve.impl import _decide_group
        a = self._c("A", 1, date(2023, 1, 1))
        winner, rule, decisions = _decide_group([a], None)
        assert winner == "A"

    def test_winner_beats_all(self):
        from truthguard.resolve.impl import _decide_group
        a = self._c("A", 3, date(2023, 1, 1))
        b = self._c("B", 2, date(2023, 1, 1))
        c = self._c("C", 1, date(2023, 1, 1))
        winner, rule, decisions = _decide_group([a, b, c], None)
        assert winner == "A"
        assert rule == "authority"

    def test_any_abstain_aborts_group(self):
        from truthguard.resolve.impl import _decide_group
        a = self._c("A", 1, date(2023, 1, 1))
        b = _clause("B", "text", authority_rank=None)  # will cause abstain_missing
        c = self._c("C", 2, date(2023, 1, 1))
        winner, rule, decisions = _decide_group([a, b, c], None)
        assert winner is None
        assert "abstain" in rule


# ---------------------------------------------------------------------------
# TestExtractMissingFields
# ---------------------------------------------------------------------------

class TestExtractMissingFields:
    def test_extracts_effective_date(self):
        d = Decision(winner=None, losers=[], rule="abstain_missing",
                     explanation="Cannot decide: X has no effective_date.")
        assert "effective_date" in _extract_missing_fields([d])

    def test_extracts_authority_rank(self):
        d = Decision(winner=None, losers=[], rule="abstain_missing",
                     explanation="Cannot decide: X has no authority_rank.")
        assert "authority_rank" in _extract_missing_fields([d])

    def test_no_abstain_decision_returns_unknown(self):
        d = Decision(winner="A", losers=["B"], rule="supersedes", explanation="A supersedes B.")
        assert _extract_missing_fields([d]) == "unknown"


# ---------------------------------------------------------------------------
# TestBuildAnswerText
# ---------------------------------------------------------------------------

class TestBuildAnswerText:
    def test_supported_uses_draft(self):
        draft = _draft("The answer is 20 days.", "C1")
        cm = {"C1": _clause("C1", "source", value_text="20 days")}
        result = _build_answer_text(draft, ["C1"], cm, Status.SUPPORTED, [])
        assert "20 days" in result

    def test_conflict_resolved_uses_winner_value_text(self):
        draft = _draft("varies", "C1", "C2")
        cm = {
            "C1": _clause("C1", "source", value_text="₹3,000"),
            "C2": _clause("C2", "source", value_text="₹5,000"),
        }
        result = _build_answer_text(draft, ["C1"], cm, Status.CONFLICT_RESOLVED, [])
        assert "₹3,000" in result

    def test_resolved_by_scope_shows_all(self):
        draft = _draft("varies", "G", "M")
        g = _clause("G", "source", scope="*", value_text="₹3,000")
        m = _clause("M", "source", scope="location=mumbai", value_text="₹4,000")
        cm = {"G": g, "M": m}
        result = _build_answer_text(draft, ["G", "M"], cm, Status.RESOLVED_BY_SCOPE, [[g, m]])
        assert "₹3,000" in result
        assert "₹4,000" in result
        assert "otherwise" in result

    def test_unresolved_prefix(self):
        result = _build_answer_text(_draft("Draft."), [], {}, Status.UNRESOLVED, [])
        assert "disagree" in result.lower() or "cannot" in result.lower()


# ---------------------------------------------------------------------------
# Integration: run() — demo questions from §8.3
# ---------------------------------------------------------------------------

class TestDemo:
    """End-to-end for the four required demo questions."""

    def test_demo1_supported_leave_days(self):
        """Demo Q1: 'How many paid leave days?' → SUPPORTED."""
        conn = _setup()
        _insert_clause(conn, "LEAVE#1", "D", "Employees get 20 paid leave days per year.",
                       concept_id="leave_days", value_num=20, value_text="20")

        c = _clause("LEAVE#1", "Employees get 20 paid leave days per year.",
                    concept_id="leave_days", value_num=20, value_text="20")
        state = _state(
            "How many paid leave days do employees get?",
            retrieval=_retrieval(c),
            draft=_draft("Employees get 20 paid leave days per year.", "LEAVE#1"),
            findings=[],
        )
        impl_run(state)
        assert state.verdict.status == Status.SUPPORTED
        assert "LEAVE#1" in state.verdict.applies

    def test_demo2_conflict_resolved_supersedes(self):
        """Demo Q2: expense limit → CONFLICT_RESOLVED (supersedes), winner A1."""
        conn = _setup()
        _insert_clause(conn, "EXP-V1#1", "D", "Manager approval limit is $5,000.",
                       concept_id="approval_limit", value_num=5000, value_text="$5,000",
                       authority_rank=1, effective_date=date(2023, 1, 1))
        _insert_clause(conn, "EXP-AMD#1", "D", "Manager approval limit is $3,000.",
                       concept_id="approval_limit", value_num=3000, value_text="$3,000",
                       authority_rank=1, effective_date=date(2024, 1, 1),
                       supersedes="EXP-V1#1")

        old_c = _clause("EXP-V1#1", "Manager approval limit is $5,000.",
                        concept_id="approval_limit", value_num=5000, value_text="$5,000",
                        authority_rank=1, effective_date=date(2023, 1, 1))
        new_c = _clause("EXP-AMD#1", "Manager approval limit is $3,000.",
                        concept_id="approval_limit", value_num=3000, value_text="$3,000",
                        authority_rank=1, effective_date=date(2024, 1, 1),
                        supersedes="EXP-V1#1")

        state = _state(
            "What is a manager's expense approval limit?",
            retrieval=_retrieval(old_c, new_c),
            draft=_draft("Limits differ: $5,000 (old) and $3,000 (new).", "EXP-V1#1", "EXP-AMD#1"),
            findings=[_finding("EXP-V1#1", "EXP-AMD#1")],
        )
        impl_run(state)
        assert state.verdict.status == Status.CONFLICT_RESOLVED
        assert state.verdict.applies == ["EXP-AMD#1"]
        # Both sources shown
        assert "EXP-V1#1" in state.verdict.shown_sources
        assert "EXP-AMD#1" in state.verdict.shown_sources
        assert state.verdict.decisions[0].rule == "supersedes"

    def test_demo3_resolved_by_scope(self):
        """Demo Q3: Mumbai travel expense → RESOLVED_BY_SCOPE."""
        conn = _setup()
        _insert_clause(conn, "GEN#1", "D", "Manager approval limit is $3,000.",
                       concept_id="approval_limit", value_num=3000, value_text="$3,000",
                       scope="*", authority_rank=1, effective_date=date(2023, 1, 1))
        _insert_clause(conn, "MUM#1", "D", "Mumbai travel expense limit is $4,000.",
                       concept_id="approval_limit", value_num=4000, value_text="$4,000",
                       scope="location=mumbai", authority_rank=1, effective_date=date(2023, 1, 1))

        gen_c = _clause("GEN#1", "Manager approval limit is $3,000.",
                        concept_id="approval_limit", value_num=3000, value_text="$3,000",
                        scope="*", authority_rank=1, effective_date=date(2023, 1, 1))
        mum_c = _clause("MUM#1", "Mumbai travel expense limit is $4,000.",
                        concept_id="approval_limit", value_num=4000, value_text="$4,000",
                        scope="location=mumbai", authority_rank=1, effective_date=date(2023, 1, 1))

        # question_scope = "*" (general question) → RESOLVED_BY_SCOPE
        state = _state(
            "Can a Mumbai manager approve a $3,500 travel expense?",
            retrieval=_retrieval(gen_c, mum_c, q_scope="*"),
            draft=_draft("Limits differ by scope.", "GEN#1", "MUM#1"),
            findings=[_finding("GEN#1", "MUM#1")],
        )
        impl_run(state)
        assert state.verdict.status == Status.RESOLVED_BY_SCOPE
        assert len(state.verdict.decisions) >= 1
        assert state.verdict.decisions[0].rule == "scope"
        # Both sources shown
        assert "GEN#1" in state.verdict.shown_sources
        assert "MUM#1" in state.verdict.shown_sources

    def test_demo4_unresolved_then_conflict_resolved(self):
        """Demo Q4: remote work → UNRESOLVED, then CONFLICT_RESOLVED after admin fix."""
        conn = _setup()
        _insert_clause(conn, "RW-OLD#1", "D", "Max remote work is 2 days per week.",
                       concept_id="remote_work", value_num=2, value_text="2 days",
                       authority_rank=1, effective_date=date(2022, 1, 1))
        _insert_clause(conn, "RW-NEW#1", "D", "Remote work limit increased to 3 days per week.",
                       concept_id="remote_work", value_num=3, value_text="3 days",
                       authority_rank=None, effective_date=None)  # missing fields

        old_c = _clause("RW-OLD#1", "Max remote work is 2 days per week.",
                        concept_id="remote_work", value_num=2, value_text="2 days",
                        authority_rank=1, effective_date=date(2022, 1, 1))
        new_c = _clause("RW-NEW#1", "Remote work limit increased to 3 days per week.",
                        concept_id="remote_work", value_num=3, value_text="3 days",
                        authority_rank=None, effective_date=None)

        state1 = _state(
            "How many days can employees work remotely?",
            retrieval=_retrieval(old_c, new_c),
            draft=_draft("Remote work: 2 or 3 days.", "RW-OLD#1", "RW-NEW#1"),
            findings=[_finding("RW-OLD#1", "RW-NEW#1", kind=FindingType.STALE)],
        )
        impl_run(state1)
        assert state1.verdict.status == Status.UNRESOLVED
        assert state1.verdict.review_item_ids  # review item created
        assert "effective_date" in state1.verdict.decisions[0].explanation \
            or "authority_rank" in state1.verdict.decisions[0].explanation

        # Admin fix: add authority_rank + effective_date to RW-NEW#1
        conn.execute(
            "UPDATE clauses SET authority_rank = 1, effective_date = '2024-06-01' WHERE clause_id = 'RW-NEW#1'"
        )
        item_id = state1.verdict.review_item_ids[0]
        conn.execute(
            "UPDATE review_queue SET resolved_at = current_timestamp, resolved_by = 'u-admin' WHERE item_id = ?",
            [item_id],
        )

        # Second run with updated clauses
        old_c2 = old_c
        new_c2 = _clause("RW-NEW#1", "Remote work limit increased to 3 days per week.",
                         concept_id="remote_work", value_num=3, value_text="3 days",
                         authority_rank=1, effective_date=date(2024, 6, 1))

        state2 = _state(
            "How many days can employees work remotely?",
            retrieval=_retrieval(old_c2, new_c2),
            draft=_draft("Remote work: 2 or 3 days.", "RW-OLD#1", "RW-NEW#1"),
            findings=[_finding("RW-OLD#1", "RW-NEW#1", kind=FindingType.STALE)],
        )
        impl_run(state2)
        assert state2.verdict.status == Status.CONFLICT_RESOLVED
        assert "RW-NEW#1" in state2.verdict.applies  # newer clause wins
        assert state2.verdict.decisions[-1].rule == "recency"


# ---------------------------------------------------------------------------
# Integration: run() — special cases
# ---------------------------------------------------------------------------

class TestRunSpecialCases:
    def test_no_findings_supported(self):
        _setup()
        c = _clause("C1", "text", concept_id="x")
        state = _state("q?", _retrieval(c), _draft("text", "C1"), [])
        impl_run(state)
        assert state.verdict.status == Status.SUPPORTED

    def test_no_draft_unresolved(self):
        _setup()
        c = _clause("C1", "text", concept_id="x")
        state = _state("q?", _retrieval(c), None, [_finding("C1")])
        impl_run(state)
        assert state.verdict.status == Status.UNRESOLVED

    def test_restricted_conflict_note(self):
        _setup()
        c = _clause("C1", "text", concept_id="x", authority_rank=1, effective_date=date(2023, 1, 1))
        restricted_finding = Finding(
            type=FindingType.CONTRADICTION, claim_id=None,
            clause_ids=[], detail="restricted source conflicts", evidence={}
        )
        state = _state("q?", _retrieval(c), _draft("text", "C1"), [restricted_finding])
        impl_run(state)
        assert "Contact Compliance" in state.verdict.answer_text
        assert "restricted" not in state.verdict.answer_text.lower() or "can't access" in state.verdict.answer_text

    def test_audit_log_written(self):
        conn = _setup()
        c = _clause("C1", "text", concept_id="x")
        state = _state("q?", _retrieval(c), _draft("text", "C1"), [])
        impl_run(state)
        rows = conn.execute("SELECT count(*) FROM audit_log").fetchone()
        assert rows[0] >= 1

    def test_shown_sources_includes_losers(self):
        conn = _setup()
        _insert_clause(conn, "A1", "D", "Limit is $5,000.",
                       concept_id="x", value_num=5000, authority_rank=1, effective_date=date(2023, 1, 1))
        _insert_clause(conn, "A2", "D", "Limit is $3,000.",
                       concept_id="x", value_num=3000, authority_rank=1, effective_date=date(2024, 1, 1),
                       supersedes="A1")

        a1 = _clause("A1", "Limit is $5,000.", concept_id="x", value_num=5000,
                     authority_rank=1, effective_date=date(2023, 1, 1))
        a2 = _clause("A2", "Limit is $3,000.", concept_id="x", value_num=3000,
                     authority_rank=1, effective_date=date(2024, 1, 1), supersedes="A1")

        state = _state("limit?", _retrieval(a1, a2),
                       _draft("varies", "A1", "A2"),
                       [_finding("A1", "A2")])
        impl_run(state)
        assert state.verdict.status == Status.CONFLICT_RESOLVED
        assert "A1" in state.verdict.shown_sources
        assert "A2" in state.verdict.shown_sources

    def test_review_queue_item_written_on_unresolved(self):
        conn = _setup()
        _insert_clause(conn, "X1", "D", "text", concept_id="x", authority_rank=None)
        _insert_clause(conn, "X2", "D", "text2", concept_id="x", authority_rank=1,
                       effective_date=date(2024, 1, 1))

        x1 = _clause("X1", "text", concept_id="x", authority_rank=None)
        x2 = _clause("X2", "text2", concept_id="x", authority_rank=1, effective_date=date(2024, 1, 1))

        state = _state("q?", _retrieval(x1, x2), _draft("both", "X1", "X2"), [_finding("X1", "X2")])
        impl_run(state)
        assert state.verdict.status == Status.UNRESOLVED
        assert len(state.verdict.review_item_ids) == 1
        row = conn.execute(
            "SELECT missing_fields FROM review_queue WHERE item_id = ?",
            [state.verdict.review_item_ids[0]],
        ).fetchone()
        assert row is not None
        assert "authority_rank" in row[0]
