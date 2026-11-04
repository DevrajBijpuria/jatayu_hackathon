# Phase 3 — Synthesizer

**Owner:** TBD  
**Folder:** `truthguard/synthesize/`

## What this phase does

Drafts an answer from retrieved passages, split into atomic claims each citing its source clause(s).

See AGENTS.md §6 (Phase 3) for the full specification.

## Current state

`baseline.py` is active (`BASELINE_SYNTHESIZE=true`). Returns the top candidate's `source_text` as a single claim — no LLM call.

## What the real impl must do

1. Build the prompt with passages wrapped in `<document id="...">` tags.
2. Call the LLM (small model for single-clause / no conflict; large model otherwise).
3. Parse the response into `Draft` with atomic claims.
4. Validate: reject claims with empty `clause_ids` or unretieved ids.
5. Grounding check: every number in a claim must appear in a cited passage.
6. On violation: retry once; if still fails, drop the bad claim with an UNSUPPORTED note.

## Pitfalls

- The Synthesizer is intentionally naive about conflicts — that is the Critic's job. Do NOT add precedence logic here.
- Never blend or average values from different clauses.
