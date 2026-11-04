# Phase 5 — Rule-Based Resolver, Review Queue, Audit Log & UI

**Owner:** TBD  
**Folders:** `truthguard/resolve/`, `truthguard/api/`, `web/`

## What this phase does

Decides with fixed, explainable rules which source applies; abstains when the rules can't decide; records everything; shows it in the UI.

See AGENTS.md §6 (Phase 5) for the full specification.

## Current state

`baseline.py` is active (`BASELINE_RESOLVE=true`). If findings exist, picks the clause with the latest `effective_date`; otherwise returns the draft as `SUPPORTED`. Writes to `audit_log`.

## What the real impl must do

The `decide(a, b, as_of)` function — in pure Python, no LLM — applying rules in order:
1. Scope separation.
2. Explicit supersedes link.
3. Authority rank.
4. Specificity (number of scope tags).
5. Recency (effective_date).
6. Abstain on tie or missing data.

Plus:
- Final-wording LLM call (small model) with value validation.
- `review_queue` writes for UNRESOLVED verdicts.
- `POST /review/{id}` flow to re-check after fixing a clause.
- SSO (behind `ENABLE_SSO`): Keycloak + JWT verification.
- UI: Next.js + shadcn/ui (three screens: Ask, Conflicts, Review Queue).

## Pitfalls

- **Never call the LLM inside `decide`.** The rule is deterministic Python only.
- NULL fields are where bugs hide — test every field being NULL.
- `authority_rank` comes from `authority_config`, not from the LLM.
