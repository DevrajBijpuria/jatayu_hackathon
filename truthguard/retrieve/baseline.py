"""Phase 2 baseline — BM25 only, top-5, no rewrite, no family expansion.

Uses rank_bm25 (pure Python) so no GPU or model download is needed.
"""
from __future__ import annotations

import re

from rank_bm25 import BM25Okapi  # type: ignore

from truthguard.contracts import (
    Clause,
    RetrievalResult,
    RetrievedClause,
    TGState,
)
from truthguard.db.conn import get_conn


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def run(state: TGState) -> TGState:
    conn = get_conn()

    # Fetch all active clauses the user can access
    rows = conn.execute(
        """SELECT clause_id, doc_id, source_text, language, text_en, concept_id,
                  subject, clause_type, value_num, value_unit, value_text,
                  condition_text, scope, issuer, authority_rank, effective_date,
                  supersedes, access_level, extract_conf, status
           FROM clauses
           WHERE status = 'active'
             AND access_level IN ({placeholders})
        """.format(placeholders=",".join("?" * len(state.user.access_levels))),
        state.user.access_levels,
    ).fetchall()

    if not rows:
        state.retrieval = RetrievalResult(
            concept_id=None,
            candidates=[],
            family=[],
        )
        return state

    clauses = [
        Clause(
            clause_id=r[0],
            doc_id=r[1],
            source_text=r[2],
            language=r[3],
            text_en=r[4],
            concept_id=r[5],
            subject=r[6],
            clause_type=r[7],
            value_num=float(r[8]) if r[8] is not None else None,
            value_unit=r[9],
            value_text=r[10],
            condition_text=r[11],
            scope=r[12] or "*",
            issuer=r[13],
            authority_rank=int(r[14]) if r[14] is not None else None,
            effective_date=r[15],
            supersedes=r[16],
            access_level=r[17] or "all",
            extract_conf=float(r[18]) if r[18] is not None else None,
            status=r[19] or "active",
        )
        for r in rows
    ]

    corpus = [_tokenize(c.source_text) for c in clauses]
    bm25 = BM25Okapi(corpus)
    query_tokens = _tokenize(state.question)
    scores = bm25.get_scores(query_tokens)

    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:5]

    candidates = [
        RetrievedClause(clause=clauses[i], score=float(scores[i]), via="search")
        for i in top_indices
    ]

    # Pick the most common concept_id among candidates
    concept_counts: dict[str, int] = {}
    for rc in candidates:
        cid = rc.clause.concept_id
        if cid:
            concept_counts[cid] = concept_counts.get(cid, 0) + 1
    concept_id = max(concept_counts, key=lambda k: concept_counts[k]) if concept_counts else None

    state.retrieval = RetrievalResult(
        concept_id=concept_id,
        candidates=candidates,
        family=candidates,  # baseline: family == candidates
    )
    return state
