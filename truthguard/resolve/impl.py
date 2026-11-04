"""Phase 5 — Rule-Based Resolver (real implementation).

Deterministic pairwise precedence, no LLM inside decide().
See AGENTS.md §6 Phase 5.
"""
from __future__ import annotations

import itertools
import uuid
from datetime import date, datetime
from typing import Any

from truthguard import config
from truthguard.contracts import (
    Clause,
    Decision,
    Draft,
    Finding,
    FindingType,
    Status,
    TGState,
    Verdict,
)
from truthguard.db.conn import get_conn


def _today() -> date:
    return datetime.utcnow().date()


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def _parse_scope_tags(scope: str) -> dict[str, str]:
    """'k1=v1;k2=v2' → {'k1': 'v1', 'k2': 'v2'}.  '*' → {}."""
    if not scope or scope == "*":
        return {}
    result: dict[str, str] = {}
    for part in scope.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            result[k.strip()] = v.strip()
    return result


def specificity(clause: Clause) -> int:
    """Number of scope tags (0 for '*')."""
    return len(_parse_scope_tags(clause.scope))


def in_force(clause: Clause, ref: date) -> bool:
    """True when clause.effective_date is set and ≤ ref."""
    return clause.effective_date is not None and clause.effective_date <= ref


def _covers_question(clause_scope: str, q_tags: dict[str, str]) -> bool:
    """True if the clause can apply to a question with the given scope tags."""
    c_tags = _parse_scope_tags(clause_scope)
    if not c_tags:
        return True  # scope=* covers all questions
    if not q_tags:
        return True  # no question scope → all clauses potentially apply
    # Clause is specific: it covers the question only if its tags are a subset
    return all(q_tags.get(k) == v for k, v in c_tags.items())


# ---------------------------------------------------------------------------
# Core: decide (spec verbatim, no LLM)
# ---------------------------------------------------------------------------

def decide(a: Clause, b: Clause, as_of: date | None) -> Decision:
    # Rule 2: explicit supersession
    if a.supersedes == b.clause_id:
        return Decision(
            winner=a.clause_id, losers=[b.clause_id], rule="supersedes",
            explanation=f"{a.clause_id} explicitly supersedes {b.clause_id}.",
        )
    if b.supersedes == a.clause_id:
        return Decision(
            winner=b.clause_id, losers=[a.clause_id], rule="supersedes",
            explanation=f"{b.clause_id} explicitly supersedes {a.clause_id}.",
        )

    # Rule 3a / rule 4: authority rank
    if a.authority_rank is None or b.authority_rank is None:
        missing = "; ".join(
            f"{c.clause_id} has no authority_rank"
            for c in (a, b) if c.authority_rank is None
        )
        return Decision(
            winner=None, losers=[a.clause_id, b.clause_id], rule="abstain_missing",
            explanation=f"Cannot decide: {missing}.",
        )
    if a.authority_rank != b.authority_rank:
        w, loser = (a, b) if a.authority_rank > b.authority_rank else (b, a)
        return Decision(
            winner=w.clause_id, losers=[loser.clause_id], rule="authority",
            explanation=(
                f"{w.clause_id} (rank {w.authority_rank}) has higher authority "
                f"than {loser.clause_id} (rank {loser.authority_rank})."
            ),
        )

    # Rule 3b: specificity
    sa, sb = specificity(a), specificity(b)
    if sa != sb:
        w, loser = (a, b) if sa > sb else (b, a)
        sw, sl = (sa, sb) if sa > sb else (sb, sa)
        return Decision(
            winner=w.clause_id, losers=[loser.clause_id], rule="specificity",
            explanation=(
                f"{w.clause_id} ({sw} scope tag(s)) is more specific "
                f"than {loser.clause_id} ({sl} scope tag(s))."
            ),
        )

    # Rule 3c / rule 4: recency
    ref = as_of or _today()
    if a.effective_date is None or b.effective_date is None:
        missing = "; ".join(
            f"{c.clause_id} has no effective_date"
            for c in (a, b) if c.effective_date is None
        )
        return Decision(
            winner=None, losers=[a.clause_id, b.clause_id], rule="abstain_missing",
            explanation=f"Cannot decide: {missing}.",
        )
    a_in, b_in = in_force(a, ref), in_force(b, ref)
    if a_in != b_in:
        w, loser = (a, b) if a_in else (b, a)
        return Decision(
            winner=w.clause_id, losers=[loser.clause_id], rule="recency",
            explanation=(
                f"{w.clause_id} (effective {w.effective_date}) is in force; "
                f"{loser.clause_id} (effective {loser.effective_date}) is not."
            ),
        )
    if a.effective_date != b.effective_date:
        w, loser = (a, b) if a.effective_date > b.effective_date else (b, a)
        return Decision(
            winner=w.clause_id, losers=[loser.clause_id], rule="recency",
            explanation=(
                f"{w.clause_id} (effective {w.effective_date}) is more recent "
                f"than {loser.clause_id} (effective {loser.effective_date})."
            ),
        )

    return Decision(
        winner=None, losers=[a.clause_id, b.clause_id], rule="abstain_tie",
        explanation=(
            f"{a.clause_id} and {b.clause_id} have equal authority, "
            f"specificity, and effective date."
        ),
    )


# ---------------------------------------------------------------------------
# Multi-clause group decision
# ---------------------------------------------------------------------------

def _decide_group(
    clauses: list[Clause], as_of: date | None
) -> tuple[str | None, str, list[Decision]]:
    """All-pairs comparison. Returns (winner_id or None, final_rule, all_decisions)."""
    if len(clauses) == 1:
        return clauses[0].clause_id, "single", []

    all_decisions: list[Decision] = []
    for a, b in itertools.combinations(clauses, 2):
        d = decide(a, b, as_of)
        all_decisions.append(d)
        if d.winner is None:
            return None, d.rule, all_decisions

    # Count wins: winner must beat all others (n-1 wins)
    n = len(clauses)
    wins: dict[str, int] = {}
    for d in all_decisions:
        if d.winner:
            wins[d.winner] = wins.get(d.winner, 0) + 1

    winner_id = next((cid for cid, w in wins.items() if w == n - 1), None)
    if winner_id is None:
        return None, "abstain_tie", all_decisions

    final_rule = next(
        (d.rule for d in reversed(all_decisions) if d.winner == winner_id),
        "supersedes",
    )
    return winner_id, final_rule, all_decisions


# ---------------------------------------------------------------------------
# Scope step
# ---------------------------------------------------------------------------

def _apply_scope_step(
    clauses: list[Clause], q_scope: str
) -> tuple[list[Clause], bool]:
    """Filter by question scope; return (kept, resolved_by_scope)."""
    q_tags = _parse_scope_tags(q_scope)
    has_q_scope = bool(q_tags)

    kept = (
        [c for c in clauses if _covers_question(c.scope, q_tags)]
        if has_q_scope
        else clauses
    )

    # RESOLVED_BY_SCOPE: no question scope + clauses have different scopes
    if not has_q_scope and kept:
        scopes = {c.scope for c in kept}
        if len(scopes) > 1 and any(c.scope != "*" for c in kept):
            return kept, True

    return kept, False


# ---------------------------------------------------------------------------
# Clause map builder
# ---------------------------------------------------------------------------

def _build_clause_map(state: TGState, conn: Any) -> dict[str, Clause]:
    m: dict[str, Clause] = {}
    if state.retrieval:
        for rc in state.retrieval.family + state.retrieval.candidates:
            m[rc.clause.clause_id] = rc.clause

    needed = {cid for f in state.findings for cid in f.clause_ids if cid} - set(m.keys())
    if needed:
        ph = ",".join("?" * len(needed))
        rows = conn.execute(
            f"""SELECT clause_id, doc_id, source_text, language, text_en,
                       concept_id, subject, clause_type, value_num, value_unit,
                       value_text, condition_text, scope, issuer, authority_rank,
                       effective_date, supersedes, access_level, extract_conf, status
                FROM clauses WHERE clause_id IN ({ph})""",
            list(needed),
        ).fetchall()
        for r in rows:
            m[r[0]] = Clause(
                clause_id=r[0], doc_id=r[1], source_text=r[2],
                language=r[3], text_en=r[4], concept_id=r[5],
                subject=r[6], clause_type=r[7],
                value_num=float(r[8]) if r[8] is not None else None,
                value_unit=r[9], value_text=r[10], condition_text=r[11],
                scope=r[12] or "*", issuer=r[13],
                authority_rank=int(r[14]) if r[14] is not None else None,
                effective_date=r[15], supersedes=r[16],
                access_level=r[17] or "all",
                extract_conf=float(r[18]) if r[18] is not None else None,
                status=r[19] or "active",
            )
    return m


# ---------------------------------------------------------------------------
# Group conflict clauses by concept
# ---------------------------------------------------------------------------

def _group_conflict_clauses(
    findings: list[Finding], clause_map: dict[str, Clause]
) -> dict[str, list[Clause]]:
    """Group CONTRADICTION/STALE clause_ids by concept_id."""
    groups: dict[str, list[str]] = {}
    for f in findings:
        if f.type not in (FindingType.CONTRADICTION, FindingType.STALE):
            continue
        if not f.clause_ids:
            continue
        concept_id = next(
            (
                clause_map[cid].concept_id
                for cid in f.clause_ids
                if cid in clause_map and clause_map[cid].concept_id
            ),
            f"finding_{f.clause_ids[0]}",
        )
        seen = groups.setdefault(concept_id, [])
        for cid in f.clause_ids:
            if cid not in seen:
                seen.append(cid)

    return {
        concept_id: [clause_map[cid] for cid in cids if cid in clause_map]
        for concept_id, cids in groups.items()
        if any(cid in clause_map for cid in cids)
    }


# ---------------------------------------------------------------------------
# Missing fields extraction
# ---------------------------------------------------------------------------

def _extract_missing_fields(decisions: list[Decision]) -> str:
    fields: list[str] = []
    for d in decisions:
        if d.rule == "abstain_missing":
            if "effective_date" in d.explanation and "effective_date" not in fields:
                fields.append("effective_date")
            if "authority_rank" in d.explanation and "authority_rank" not in fields:
                fields.append("authority_rank")
    return ";".join(fields) if fields else "unknown"


# ---------------------------------------------------------------------------
# Answer text builder
# ---------------------------------------------------------------------------

def _build_answer_text(
    draft: Draft | None,
    winner_ids: list[str],
    clause_map: dict[str, Clause],
    status: Status,
    scope_groups: list[list[Clause]],
) -> str:
    if status == Status.SUPPORTED:
        return draft.answer_text if draft else "Not found in the documents."

    if status == Status.CONFLICT_RESOLVED:
        if winner_ids:
            w = clause_map.get(winner_ids[0])
            if w:
                return w.value_text or w.source_text
        return draft.answer_text if draft else "Resolved."

    if status == Status.RESOLVED_BY_SCOPE:
        parts: list[str] = []
        for group in scope_groups:
            for c in group:
                label = c.scope if c.scope != "*" else "otherwise"
                val = (
                    c.value_text
                    or (str(int(c.value_num)) if c.value_num is not None else None)
                    or c.source_text[:80]
                )
                parts.append(f"{val} ({label})")
        return "; ".join(parts) if parts else (draft.answer_text if draft else "Scope-dependent.")

    # UNRESOLVED
    return (
        "The sources disagree and cannot be automatically resolved. "
        + (draft.answer_text if draft else "")
    ).strip()


# ---------------------------------------------------------------------------
# DB writes
# ---------------------------------------------------------------------------

def _write_review_queue(conn: Any, clause_id: str, missing_fields: str) -> str:
    item_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO review_queue (item_id, clause_id, reason, missing_fields) VALUES (?, ?, ?, ?)",
        [item_id, clause_id, "unresolved_conflict", missing_fields],
    )
    return item_id


def _write_audit_log(state: TGState) -> None:
    try:
        conn = get_conn()
        log_id = str(uuid.uuid4())
        verdict = state.verdict
        conn.execute(
            """INSERT INTO audit_log
               (log_id, user_id, question, as_of, status, answer, trace_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                log_id,
                state.user.user_id,
                state.question,
                state.as_of,
                verdict.status.value if verdict else None,
                verdict.answer_text if verdict else None,
                state.model_dump_json(),
            ],
        )
    except Exception:
        pass  # audit failure must never break the response


def _recompute_conflicts(conn: Any, concept_id: str) -> None:
    """Delete and reinsert value_mismatch conflicts for all active clauses in the concept."""
    rows = conn.execute(
        "SELECT clause_id, value_num FROM clauses WHERE concept_id = ? AND status = 'active'",
        [concept_id],
    ).fetchall()
    if not rows:
        return

    cids = [r[0] for r in rows]
    ph = ",".join("?" * len(cids))
    conn.execute(
        f"DELETE FROM conflicts WHERE kind = 'value_mismatch' AND clause_a IN ({ph}) AND clause_b IN ({ph})",
        cids + cids,
    )
    for (id_a, vn_a), (id_b, vn_b) in itertools.combinations(rows, 2):
        if vn_a is not None and vn_b is not None and vn_a != vn_b:
            conflict_id = f"CF-{id_a[:16]}-{id_b[:16]}"
            try:
                conn.execute(
                    "INSERT INTO conflicts (conflict_id, clause_a, clause_b, kind, score) VALUES (?, ?, ?, 'value_mismatch', 1.0)",
                    [conflict_id, id_a, id_b],
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Optional LLM rephrasing (validates value is preserved)
# ---------------------------------------------------------------------------

def _rephrase_answer(state: TGState, clause_map: dict[str, Clause]) -> str | None:
    if not config.LLM_API_KEY or state.verdict is None:
        return None
    try:
        import truthguard.llm as llm
        from truthguard.lang import grounding_check

        rule = state.verdict.decisions[0].rule if state.verdict.decisions else ""
        raw = llm.complete(
            "final_answer",
            {
                "status": state.verdict.status.value,
                "answer_text": state.verdict.answer_text,
                "rule": rule,
                "shown_sources": ", ".join(state.verdict.shown_sources),
                "question_language": state.question_language,
            },
            model="small",
        )
        rephrased = str(raw)

        # Validate that decided values appear in the rephrased text
        for cid in state.verdict.applies:
            c = clause_map.get(cid)
            if c and c.value_num is not None:
                val = float(int(c.value_num) if c.value_num == int(c.value_num) else c.value_num)
                if not grounding_check(val, rephrased):
                    return None  # value changed — discard rephrasing
        return rephrased
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Entry point (LangGraph node)
# ---------------------------------------------------------------------------

def run(state: TGState) -> TGState:
    conn = get_conn()
    draft = state.draft
    clause_map = _build_clause_map(state, conn)

    # 1. No findings → SUPPORTED
    if not state.findings:
        clause_ids = [cid for claim in (draft.claims if draft else []) for cid in claim.clause_ids]
        state.verdict = Verdict(
            status=Status.SUPPORTED,
            answer_text=draft.answer_text if draft else "Not found in the documents.",
            applies=clause_ids,
            shown_sources=clause_ids,
            decisions=[],
        )
        _write_audit_log(state)
        return state

    # 2. No draft → UNRESOLVED
    if draft is None or not draft.claims:
        state.verdict = Verdict(
            status=Status.UNRESOLVED,
            answer_text="No answer could be drafted from the available documents.",
            applies=[],
            shown_sources=[],
            decisions=[Decision(winner=None, losers=[], rule="abstain_missing", explanation="No draft was produced.")],
        )
        _write_audit_log(state)
        return state

    # 3. Group CONTRADICTION/STALE findings by concept
    groups = _group_conflict_clauses(state.findings, clause_map)
    has_restricted = any(
        f.type == FindingType.CONTRADICTION and f.clause_ids == [] and f.detail == "restricted source conflicts"
        for f in state.findings
    )

    all_decisions: list[Decision] = []
    review_item_ids: list[str] = []
    winner_ids: list[str] = []
    scope_groups: list[list[Clause]] = []
    overall_status = Status.SUPPORTED

    q_scope = (state.retrieval.question_scope if state.retrieval else "*") or "*"

    for _concept_id, group_clauses in groups.items():
        if not group_clauses:
            continue

        filtered, resolved_by_scope = _apply_scope_step(group_clauses, q_scope)

        if resolved_by_scope:
            if overall_status not in (Status.UNRESOLVED,):
                overall_status = Status.RESOLVED_BY_SCOPE
            scope_groups.append(filtered)
            winner_ids.extend(c.clause_id for c in filtered)
            all_decisions.append(Decision(
                winner=None, losers=[], rule="scope",
                explanation="Sources apply to different scopes: "
                            + "; ".join(f"{c.clause_id} (scope={c.scope})" for c in filtered),
            ))
            continue

        if not filtered:
            continue

        if len(filtered) == 1:
            if overall_status == Status.SUPPORTED:
                overall_status = Status.CONFLICT_RESOLVED
            winner_ids.append(filtered[0].clause_id)
            continue

        winner_id, _rule, decisions = _decide_group(filtered, state.as_of)
        all_decisions.extend(decisions)

        if winner_id is None:
            overall_status = Status.UNRESOLVED
            missing_fields = _extract_missing_fields(decisions)
            item_id = _write_review_queue(conn, filtered[0].clause_id, missing_fields)
            review_item_ids.append(item_id)
        else:
            if overall_status not in (Status.UNRESOLVED, Status.RESOLVED_BY_SCOPE):
                overall_status = Status.CONFLICT_RESOLVED
            winner_ids.append(winner_id)

    # Collect shown_sources from all findings
    shown_sources = list(dict.fromkeys(
        cid for f in state.findings for cid in f.clause_ids if cid
    ))
    if not shown_sources:
        shown_sources = [cid for claim in draft.claims for cid in claim.clause_ids]

    answer_text = _build_answer_text(draft, winner_ids, clause_map, overall_status, scope_groups)

    if has_restricted:
        answer_text += " A source you can't access may say otherwise. Contact Compliance."

    state.verdict = Verdict(
        status=overall_status,
        answer_text=answer_text,
        applies=winner_ids,
        shown_sources=shown_sources,
        decisions=all_decisions,
        review_item_ids=review_item_ids,
    )

    # Optional LLM rephrase (validates value is preserved)
    if config.LLM_API_KEY:
        rephrased = _rephrase_answer(state, clause_map)
        if rephrased:
            state.verdict = state.verdict.model_copy(update={"answer_text": rephrased})

    _write_audit_log(state)
    return state
