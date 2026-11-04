# Phase 2 — Family-Aware Retriever

**Owner:** TBD  
**Folder:** `truthguard/retrieve/`

## What this phase does

Returns passages relevant to the question and every version of the matched rule, respecting user permissions and any "as of" date.

See AGENTS.md §6 (Phase 2) for the full specification.

## Current state

`baseline.py` is active (`BASELINE_RETRIEVE=true`). BM25-only, top-5, no rewrite, no family expansion, permission filter only.

## What the real impl must do

1. LLM query parse (rewrites, concept phrase, scope tags, as_of).
2. Hybrid BM25 + FAISS search with reciprocal rank fusion.
3. Permission + as_of filters.
4. Reranker (`bge-reranker-v2-m3`).
5. Concept pick + family expansion (ALL versions for the concept).
6. Restricted-conflict flag (check hidden clauses).

## TODO

- [ ] Replace `impl.py` with the real implementation.
- [ ] Test cross-language retrieval (Hindi question → English clauses and vice versa).
- [ ] Verify as_of date handling keeps NULL-date clauses flagged rather than dropped.
