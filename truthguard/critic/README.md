# Phase 4 — Critic (Adversarial Agent)

**Owner:** TBD  
**Folder:** `truthguard/critic/`

## What this phase does

Actively tries to break the draft. Produces findings for contradiction, staleness, and unsupported claims — based on evidence from tool calls, not opinion.

See AGENTS.md §6 (Phase 4) for the full specification.

## Current state

`baseline.py` is active (`BASELINE_CRITIC=true`). Returns no findings — the draft passes through unchallenged.

## What the real impl must do

LangGraph node with tools:
- `compare_values(clause_ids)` — differing value_num/scope/condition_text
- `nli(text_a, text_b)` — DeBERTa NLI probabilities
- `lookup_conflicts(clause_id)` — rows from the `conflicts` table
- `find_newer(clause_id)` — newer or superseding clauses (respecting user permissions + as_of)
- `claim_supported(claim, clause_id)` — NLI entailment + number-presence check

All tool calls are **mandatory** — do not trust the LLM's "looks fine".

## Pitfalls

- Do NOT let the Critic rewrite the answer or pick a winner.
- Do NOT skip tools because the LLM thinks the draft looks correct.
- If `retrieval.restricted_conflict` is True, emit a CONTRADICTION with `clause_ids=[]`.
