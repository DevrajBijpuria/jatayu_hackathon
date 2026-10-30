"""Phase 5 baseline — naive recency picker, no rule engine, writes audit_log."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from truthguard.contracts import (
    Decision,
    Draft,
    Status,
    TGState,
    Verdict,
)
from truthguard.db.conn import get_conn


def _today() -> date:
    return datetime.utcnow().date()


def run(state: TGState) -> TGState:
    draft: Draft | None = state.draft

    if draft is None or not draft.claims:
        state.verdict = Verdict(
            status=Status.UNRESOLVED,
            answer_text="No answer could be drafted from the available documents.",
            applies=[],
            shown_sources=[],
            decisions=[
                Decision(
                    winner=None,
                    losers=[],
                    rule="abstain_missing",
                    explanation="No draft was produced.",
                )
            ],
        )
    elif state.findings:
        # Baseline: if there are findings (shouldn't happen with baseline critic),
        # pick the clause with the latest effective_date among those cited.
        all_clause_ids = [cid for claim in draft.claims for cid in claim.clause_ids]

        # Gather clauses from retrieval
        family = state.retrieval.family if state.retrieval else []
        candidates_map = {rc.clause.clause_id: rc.clause for rc in family}

        dated = [
            candidates_map[cid]
            for cid in all_clause_ids
            if cid in candidates_map and candidates_map[cid].effective_date is not None
        ]
        if dated:
            winner = max(dated, key=lambda c: c.effective_date)  # type: ignore[arg-type]
            state.verdict = Verdict(
                status=Status.CONFLICT_RESOLVED,
                answer_text=winner.source_text,
                applies=[winner.clause_id],
                shown_sources=all_clause_ids,
                decisions=[
                    Decision(
                        winner=winner.clause_id,
                        losers=[c for c in all_clause_ids if c != winner.clause_id],
                        rule="recency",
                        explanation=f"Picked the clause with the latest date: {winner.effective_date}.",
                    )
                ],
            )
        else:
            state.verdict = Verdict(
                status=Status.SUPPORTED,
                answer_text=draft.answer_text,
                applies=all_clause_ids,
                shown_sources=all_clause_ids,
                decisions=[],
            )
    else:
        # No findings — SUPPORTED
        all_clause_ids = [cid for claim in draft.claims for cid in claim.clause_ids]
        state.verdict = Verdict(
            status=Status.SUPPORTED,
            answer_text=draft.answer_text,
            applies=all_clause_ids,
            shown_sources=all_clause_ids,
            decisions=[],
        )

    _write_audit_log(state)
    return state


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
