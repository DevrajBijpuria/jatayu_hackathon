# Phase 1 — Ingest & Conflict Index

**Owner:** TBD  
**Folder:** `truthguard/ingest/`

## What this phase does

Turns raw documents into verified, structured clause rows, links versions together, and pre-computes the conflict list.

See AGENTS.md §6 (Phase 1) for the full specification, task list, and acceptance criteria.

## Current state

`baseline.py` is active (`BASELINE_INGEST=true`). It sentence-splits plain text files and stores clauses with `source_text` only — no LLM extraction, no conflict index.

## What the real impl must do

1. Parse PDF / DOCX / TXT / EML with section numbers.
2. Hindi text quality check + OCR fallback for legacy-font PDFs.
3. Injection guard (regex + optional Prompt-Guard).
4. Clause splitter preserving section numbers.
5. LLM extraction with `prompts/extract_clause.md` (large model, JSON schema).
6. Grounding check + number normaliser (`truthguard/lang/`).
7. Second extraction + agreement check.
8. Supersession regex + LLM fallback.
9. Concept vocabulary mapping.
10. Authority rank lookup.
11. FAISS + BM25 index build.
12. Conflict pre-index (SQL value_mismatch + NLI).
13. Connectors (behind `ENABLE_CONNECTORS`).

## TODO

- [ ] Replace `impl.py` with the real implementation.
- [ ] Unit-test the number normaliser heavily (₹, lakh, crore, Devanagari digits, Hindi number words).
- [ ] Verify injection detection works for both English and Hindi patterns.
