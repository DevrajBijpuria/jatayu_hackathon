"""Phase 3 — Synthesizer (real implementation).

Calls the LLM once (small or large model), validates citations and number
grounding, retries once on failure, then drops still-bad claims as UNSUPPORTED.
See AGENTS.md §6 Phase 3.
"""
from __future__ import annotations

from pydantic import BaseModel

import truthguard.llm as llm
from truthguard.contracts import (
    Claim,
    Draft,
    Finding,
    FindingType,
    RetrievalResult,
    TGState,
)
from truthguard.lang import grounding_check, numbers_in_text

# ---------------------------------------------------------------------------
# LLM response schema
# ---------------------------------------------------------------------------

class _LLMClaim(BaseModel):
    claim_id: str
    text: str
    clause_ids: list[str]


class _LLMDraft(BaseModel):
    answer_text: str
    claims: list[_LLMClaim]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LANG_NAMES = {"en": "English", "hi": "Hindi", "mixed": "Hindi and English"}

_NOT_FOUND_DRAFT = Draft(answer_text="Not found in the documents.", claims=[])


def _choose_model(retrieval: RetrievalResult) -> str:
    """Small model when family has exactly one clause and no conflicts; large otherwise."""
    if len(retrieval.family) == 1 and not retrieval.restricted_conflict:
        return "small"
    return "large"


def _format_passages(retrieval: RetrievalResult) -> str:
    """Format family + candidates as <document> blocks (deduped by clause_id)."""
    seen: set[str] = set()
    parts: list[str] = []
    for rc in retrieval.family + retrieval.candidates:
        c = rc.clause
        if c.clause_id in seen:
            continue
        seen.add(c.clause_id)
        date_attr = f' date="{c.effective_date}"' if c.effective_date else ""
        issuer_attr = f' issuer="{c.issuer}"' if c.issuer else ""
        parts.append(f'<document id="{c.clause_id}"{date_attr}{issuer_attr}>\n{c.source_text}\n</document>')
    return "\n\n".join(parts)


def _retrieved_map(retrieval: RetrievalResult) -> dict[str, object]:
    """clause_id → Clause for all retrieved clauses."""
    m = {}
    for rc in retrieval.family + retrieval.candidates:
        m[rc.clause.clause_id] = rc.clause
    return m


def _validate_claim(
    claim: _LLMClaim,
    retrieved_ids: set[str],
    clauses: dict,
) -> str | None:
    """Return an error string if the claim is invalid, else None."""
    # Allow the explicit "not found" sentinel
    if claim.text.strip().lower().startswith("not found"):
        return None

    if not claim.clause_ids:
        return "empty clause_ids"

    bad_ids = [cid for cid in claim.clause_ids if cid not in retrieved_ids]
    if bad_ids:
        return f"clause_ids not in retrieved set: {bad_ids}"

    # Number grounding: every number in claim.text must appear in a cited passage
    claim_nums = numbers_in_text(claim.text)
    for num in claim_nums:
        in_any = any(
            grounding_check(num, clauses[cid].source_text)
            for cid in claim.clause_ids
            if cid in clauses
        )
        if not in_any:
            return f"number {num} in claim text not found in cited passages"

    return None


def _call_once(
    variables: dict,
    model: str,
) -> _LLMDraft:
    result = llm.complete("synthesize", variables, model=model, json_schema=_LLMDraft)
    return _LLMDraft.model_validate(result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(state: TGState) -> TGState:
    retrieval = state.retrieval
    if not retrieval or (not retrieval.family and not retrieval.candidates):
        state.draft = _NOT_FOUND_DRAFT
        return state

    retrieved_ids = set(_retrieved_map(retrieval).keys())
    clauses = _retrieved_map(retrieval)

    lang = state.question_language or "en"
    lang_name = _LANG_NAMES.get(lang, "English")
    model = _choose_model(retrieval)
    passages = _format_passages(retrieval)
    as_of_instruction = (
        f"The user is asking about rules as they stood on {state.as_of}."
        if state.as_of
        else "Answer based on current rules."
    )

    base_vars: dict = {
        "question": state.question,
        "question_language": lang,
        "language_name": lang_name,
        "passages": passages,
        "as_of_instruction": as_of_instruction,
        "retry_note": "",
    }

    # First attempt
    try:
        draft_raw = _call_once(base_vars, model)
    except Exception as exc:
        state.draft = _NOT_FOUND_DRAFT
        state.findings.append(Finding(
            type=FindingType.UNSUPPORTED,
            claim_id=None,
            clause_ids=[],
            detail=f"Synthesizer LLM call failed: {exc}",
        ))
        return state

    # Validate first attempt
    good: list[_LLMClaim] = []
    bad: list[tuple[_LLMClaim, str]] = []
    for c in draft_raw.claims:
        err = _validate_claim(c, retrieved_ids, clauses)
        if err is None:
            good.append(c)
        else:
            bad.append((c, err))

    if bad:
        # Retry once with error details
        error_desc = "; ".join(f'claim "{c.claim_id}": {e}' for c, e in bad)
        retry_vars = {
            **base_vars,
            "retry_note": f"IMPORTANT: The previous response had these validation errors that you must fix:\n{error_desc}",
        }
        try:
            draft_raw2 = _call_once(retry_vars, model)
            good2: list[_LLMClaim] = []
            bad2: list[tuple[_LLMClaim, str]] = []
            for c in draft_raw2.claims:
                err = _validate_claim(c, retrieved_ids, clauses)
                if err is None:
                    good2.append(c)
                else:
                    bad2.append((c, err))
            final_good = good2
            final_bad = bad2
            answer_text = draft_raw2.answer_text
        except Exception:
            # Retry failed entirely; keep what was valid from the first call
            final_good = good
            final_bad = bad
            answer_text = draft_raw.answer_text
    else:
        final_good = good
        final_bad = []
        answer_text = draft_raw.answer_text

    # Drop bad claims → UNSUPPORTED findings
    for c, err in final_bad:
        state.findings.append(Finding(
            type=FindingType.UNSUPPORTED,
            claim_id=c.claim_id,
            clause_ids=c.clause_ids,
            detail=f"Claim dropped after retry: {err}",
        ))

    if not final_good:
        state.draft = _NOT_FOUND_DRAFT
        return state

    state.draft = Draft(
        answer_text=answer_text,
        claims=[Claim(claim_id=c.claim_id, text=c.text, clause_ids=c.clause_ids) for c in final_good],
    )
    return state
