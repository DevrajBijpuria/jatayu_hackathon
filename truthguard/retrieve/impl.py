"""Phase 2 — Family-Aware Retriever (real implementation).

Hybrid BM25+FAISS with RRF, pre-rerank filters, multilingual reranker,
concept selection, family expansion, and restricted-conflict flag.
See AGENTS.md §6 Phase 2.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from truthguard import config
from truthguard.contracts import Clause, RetrievalResult, RetrievedClause, TGState
from truthguard.db.conn import get_conn
from truthguard.lang import detect_language

# ---------------------------------------------------------------------------
# Question parsing
# ---------------------------------------------------------------------------

def _parse_question(state: TGState) -> tuple[list[str], str, str, date | None]:
    """Return (all_queries, question_language, scope_tags, as_of).

    Falls back to [state.question] if LLM key is not set or the call fails.
    """
    if not config.LLM_API_KEY:
        lang = detect_language(state.question)
        return [state.question], lang, "*", state.as_of

    try:
        from pydantic import BaseModel

        class _ParseResult(BaseModel):
            question_language: str = "en"
            rewrites: list[str] = []
            guessed_concept: str = ""
            scope_tags: str = ""
            as_of_date: str | None = None

        from truthguard.llm import complete
        result = complete(
            "rewrite_query",
            {"question": state.question},
            model="small",
            json_schema=_ParseResult,
        )

        lang = result.get("question_language", "en")
        rewrites = result.get("rewrites") or []
        scope = result.get("scope_tags") or "*"
        as_of_str = result.get("as_of_date")

        as_of: date | None = state.as_of
        if as_of_str and as_of is None:
            try:
                as_of = date.fromisoformat(as_of_str)
            except ValueError:
                pass

        if as_of is None and config.ENABLE_HINDI:
            from truthguard.lang import parse_hindi_date
            as_of = parse_hindi_date(state.question)

        all_queries = [state.question] + [r for r in rewrites if r and r != state.question]
        return all_queries, lang, scope or "*", as_of

    except Exception:
        lang = detect_language(state.question)
        return [state.question], lang, "*", state.as_of


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _load_or_build_index(conn) -> tuple[Any, Any, list[str]]:
    """Return (bm25, faiss_index_or_None, ordered_clause_ids).

    Loads from INDEX_DIR if the BM25 pickle exists; otherwise builds via dev_index.
    """
    idx = Path(config.INDEX_DIR)
    bm25_path = idx / "bm25.pkl"
    ids_path = idx / "clause_ids.json"

    if bm25_path.exists() and ids_path.exists():
        import pickle
        with open(bm25_path, "rb") as f:
            _bm25_data = pickle.load(f)
        if isinstance(_bm25_data, dict):
            bm25 = _bm25_data["bm25"]
            clause_ids: list[str] = _bm25_data.get("ids") or json.loads(ids_path.read_text())
        else:
            bm25 = _bm25_data
            clause_ids = json.loads(ids_path.read_text())

        faiss_index = None
        faiss_path = idx / "faiss.index"
        if faiss_path.exists():
            try:
                import faiss  # type: ignore
                faiss_index = faiss.read_index(str(faiss_path))
            except Exception:
                pass

        return bm25, faiss_index, clause_ids

    from truthguard.retrieve.dev_index import build_index
    return build_index(conn)


# ---------------------------------------------------------------------------
# BM25 search
# ---------------------------------------------------------------------------

def _bm25_search(bm25: Any, clause_ids: list[str], queries: list[str], top_k: int) -> list[list[str]]:
    ranked_lists = []
    for q in queries:
        tokens = _tokenize(q)
        scores = bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        ranked_lists.append([clause_ids[i] for i in ranked])
    return ranked_lists


# ---------------------------------------------------------------------------
# FAISS search
# ---------------------------------------------------------------------------

_embed_model_cache: Any = None


def _get_embed_model() -> Any:
    global _embed_model_cache
    if _embed_model_cache is None:
        from sentence_transformers import SentenceTransformer  # type: ignore
        _embed_model_cache = SentenceTransformer(config.EMBED_MODEL)
    return _embed_model_cache


def _faiss_search(faiss_index: Any, clause_ids: list[str], queries: list[str], top_k: int) -> list[list[str]]:
    if faiss_index is None:
        return []
    try:
        import numpy as np
        model = _get_embed_model()
        result = []
        for q in queries:
            emb = model.encode([q], normalize_embeddings=True).astype(np.float32)
            _, indices = faiss_index.search(emb, top_k)
            result.append([clause_ids[i] for i in indices[0] if 0 <= i < len(clause_ids)])
        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Reciprocal rank fusion
# ---------------------------------------------------------------------------

def _rrf(ranked_lists: list[list[str]], k: int = 60) -> dict[str, float]:
    """score = Σ 1 / (k + rank)  (rank is 1-based)."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, cid in enumerate(ranked, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return scores


# ---------------------------------------------------------------------------
# Clause fetch and filters
# ---------------------------------------------------------------------------

def _row_to_clause(r: tuple) -> Clause:
    return Clause(
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


def _fetch_clauses_by_ids(conn, clause_ids: list[str]) -> dict[str, Clause]:
    """Fetch active, non-injection-flagged clauses by id. No permission filter here."""
    if not clause_ids:
        return {}
    ph = ",".join("?" * len(clause_ids))
    rows = conn.execute(
        f"""SELECT c.clause_id, c.doc_id, c.source_text, c.language, c.text_en,
                   c.concept_id, c.subject, c.clause_type, c.value_num, c.value_unit,
                   c.value_text, c.condition_text, c.scope, c.issuer, c.authority_rank,
                   c.effective_date, c.supersedes, c.access_level, c.extract_conf, c.status
            FROM clauses c
            JOIN documents d ON c.doc_id = d.doc_id
            WHERE c.clause_id IN ({ph})
              AND c.status = 'active'
              AND d.injection_flag = FALSE
        """,
        clause_ids,
    ).fetchall()
    return {r[0]: _row_to_clause(r) for r in rows}


def _permission_ok(clause: Clause, user_access: list[str]) -> bool:
    return clause.access_level in user_access


def _as_of_ok(clause: Clause, as_of: date | None) -> bool:
    if as_of is None:
        return True
    if clause.effective_date is None:
        return True  # keep null-date clauses; Phase 4 flags them
    return clause.effective_date <= as_of


def _apply_filters(
    clauses: dict[str, Clause],
    user_access: list[str],
    as_of: date | None,
) -> dict[str, Clause]:
    """Permission + as_of filter — applied before reranking."""
    return {
        cid: c for cid, c in clauses.items()
        if _permission_ok(c, user_access) and _as_of_ok(c, as_of)
    }


# ---------------------------------------------------------------------------
# Reranker
# ---------------------------------------------------------------------------

_rerank_model_cache: Any = None


def _get_rerank_model() -> Any:
    global _rerank_model_cache
    if _rerank_model_cache is None:
        from sentence_transformers import CrossEncoder  # type: ignore
        _rerank_model_cache = CrossEncoder(config.RERANK_MODEL)
    return _rerank_model_cache


def _rerank(
    query: str,
    candidate_ids: list[str],
    clauses: dict[str, Clause],
    top_n: int,
) -> list[tuple[str, float]]:
    """Rerank by cross-encoder; falls back to RRF order if model unavailable."""
    if not candidate_ids:
        return []
    try:
        model = _get_rerank_model()
        pairs = [(query, clauses[cid].source_text) for cid in candidate_ids]
        raw_scores = model.predict(pairs)
        ranked = sorted(zip(candidate_ids, raw_scores), key=lambda x: x[1], reverse=True)
        return [(cid, float(s)) for cid, s in ranked[:top_n]]
    except Exception:
        # ponytail: BM25/RRF order used when reranker is not installed
        return [(cid, 0.0) for cid in candidate_ids[:top_n]]


# ---------------------------------------------------------------------------
# Concept selection
# ---------------------------------------------------------------------------

def _pick_concept(candidates: list[RetrievedClause]) -> str | None:
    counts: Counter[str] = Counter(
        rc.clause.concept_id for rc in candidates if rc.clause.concept_id
    )
    if not counts:
        return None
    top = counts.most_common(2)
    if len(top) == 1 or top[0][1] > top[1][1]:
        return top[0][0]
    # Tie → concept with highest rerank score wins
    best_score: dict[str, float] = {}
    for rc in candidates:
        cid = rc.clause.concept_id
        if cid and rc.score > best_score.get(cid, float("-inf")):
            best_score[cid] = rc.score
    return max((t[0] for t in top), key=lambda c: best_score.get(c, 0.0))


# ---------------------------------------------------------------------------
# Family expansion
# ---------------------------------------------------------------------------

def _expand_family(
    conn,
    concept_id: str,
    subject: str | None,
    user_access: list[str],
    as_of: date | None,
) -> list[Clause]:
    """Every active, accessible clause with this concept_id (and subject if set)."""
    ph = ",".join("?" * len(user_access))
    args: list[Any] = [concept_id] + user_access
    subject_sql = ""
    if subject:
        subject_sql = "AND c.subject = ?"
        args.append(subject)

    rows = conn.execute(
        f"""SELECT c.clause_id, c.doc_id, c.source_text, c.language, c.text_en,
                   c.concept_id, c.subject, c.clause_type, c.value_num, c.value_unit,
                   c.value_text, c.condition_text, c.scope, c.issuer, c.authority_rank,
                   c.effective_date, c.supersedes, c.access_level, c.extract_conf, c.status
            FROM clauses c
            JOIN documents d ON c.doc_id = d.doc_id
            WHERE c.concept_id = ?
              AND c.access_level IN ({ph})
              AND c.status = 'active'
              AND d.injection_flag = FALSE
              {subject_sql}
        """,
        args,
    ).fetchall()

    clauses = [_row_to_clause(r) for r in rows]
    if as_of is not None:
        clauses = [c for c in clauses if _as_of_ok(c, as_of)]
    return clauses


# ---------------------------------------------------------------------------
# Restricted-conflict flag
# ---------------------------------------------------------------------------

def _has_restricted_conflict(conn, concept_id: str, user_access: list[str]) -> bool:
    """True if a clause the user CANNOT see conflicts with one they can see."""
    rows = conn.execute(
        """SELECT ca.access_level, cb.access_level
           FROM conflicts cf
           JOIN clauses ca ON cf.clause_a = ca.clause_id
           JOIN clauses cb ON cf.clause_b = cb.clause_id
           WHERE (ca.concept_id = ? OR cb.concept_id = ?)
             AND ca.status = 'active' AND cb.status = 'active'
        """,
        [concept_id, concept_id],
    ).fetchall()

    for al_a, al_b in rows:
        if (al_a in user_access) != (al_b in user_access):
            return True
    return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(state: TGState) -> TGState:
    t0 = time.monotonic()
    conn = get_conn()

    # 1. Parse question → queries, language, scope, as_of
    queries, lang, scope_tags, as_of = _parse_question(state)
    state.question_language = lang
    if as_of is not None:
        state.as_of = as_of

    # 2. Load (or build dev) index
    bm25, faiss_index, all_clause_ids = _load_or_build_index(conn)

    if not all_clause_ids:
        state.retrieval = RetrievalResult(concept_id=None, candidates=[], family=[])
        return state

    # 3. Hybrid search + RRF
    bm25_lists = _bm25_search(bm25, all_clause_ids, queries, config.BM25_TOP_K)
    faiss_lists = _faiss_search(faiss_index, all_clause_ids, queries, config.FAISS_TOP_K)
    rrf_scores = _rrf(bm25_lists + faiss_lists)

    # 4. Fetch, then apply permission + as_of filters (before reranking)
    ordered = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)
    clauses_map = _fetch_clauses_by_ids(conn, ordered[:config.BM25_TOP_K * 2])
    filtered = _apply_filters(clauses_map, state.user.access_levels, state.as_of)

    if not filtered:
        state.retrieval = RetrievalResult(concept_id=None, candidates=[], family=[])
        return state

    # 5. Rerank top-20 → keep top-5 candidates
    top20 = [cid for cid in ordered if cid in filtered][:20]
    reranked = _rerank(state.question, top20, filtered, config.RERANK_TOP_K)
    candidates = [
        RetrievedClause(clause=filtered[cid], score=score, via="search")
        for cid, score in reranked
        if cid in filtered
    ]

    # 6. Concept selection
    concept_id = _pick_concept(candidates)

    # 7. Family expansion
    family: list[RetrievedClause] = []
    if concept_id:
        subject_ref = candidates[0].clause.subject if candidates else None
        for c in _expand_family(conn, concept_id, subject_ref, state.user.access_levels, state.as_of):
            via = "search" if any(rc.clause.clause_id == c.clause_id for rc in candidates) else "family_expansion"
            score = next((rc.score for rc in candidates if rc.clause.clause_id == c.clause_id), 0.0)
            family.append(RetrievedClause(clause=c, score=score, via=via))

    # 8. Restricted-conflict flag
    restricted = _has_restricted_conflict(conn, concept_id, state.user.access_levels) if concept_id else False

    ms = int((time.monotonic() - t0) * 1000)
    print(f"[retrieve] latency_ms={ms} candidates={len(candidates)} family={len(family)}")

    state.retrieval = RetrievalResult(
        concept_id=concept_id,
        question_scope=scope_tags,
        candidates=candidates,
        family=family if family else candidates,
        restricted_conflict=restricted,
    )
    state.rewrites = queries[1:]
    return state
