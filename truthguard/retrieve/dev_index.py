"""
# DEV ONLY — Remove this file once Phase 1 ingest produces data/index/.
#
# Builds an in-memory BM25 index (and optionally FAISS) from the clauses table.
# Used when INDEX_DIR is missing or empty; the real index is built by ingest.
"""
from __future__ import annotations

import re
from typing import Any


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def build_index(conn) -> tuple[Any, Any, list[str]]:
    """Return (bm25, faiss_index_or_None, clause_ids) built from DB clauses.

    FAISS is built only if sentence-transformers + faiss-cpu are installed;
    otherwise None is returned and the caller uses BM25 only.
    """
    rows = conn.execute(
        "SELECT clause_id, source_text FROM clauses WHERE status = 'active' ORDER BY clause_id"
    ).fetchall()

    from rank_bm25 import BM25Okapi  # type: ignore

    if not rows:
        return BM25Okapi([[""]]), None, []

    clause_ids = [r[0] for r in rows]
    texts = [r[1] or "" for r in rows]
    corpus = [_tokenize(t) for t in texts]
    bm25 = BM25Okapi(corpus)

    faiss_index = None
    try:
        import faiss  # type: ignore
        import numpy as np
        from sentence_transformers import SentenceTransformer  # type: ignore

        from truthguard import config
        model = SentenceTransformer(config.EMBED_MODEL)
        emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        emb = emb.astype(np.float32)
        faiss_index = faiss.IndexFlatIP(emb.shape[1])
        faiss_index.add(emb)
    except Exception:
        pass  # ponytail: BM25-only fallback when ML deps absent

    return bm25, faiss_index, clause_ids
