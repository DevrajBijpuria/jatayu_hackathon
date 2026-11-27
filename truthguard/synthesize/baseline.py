"""Phase 3 baseline — returns the top candidate's source_text as a single claim."""
from __future__ import annotations

import re

from truthguard.contracts import Claim, Draft, TGState

_STOPS = frozenset(
    "WHAT IS THE OF UNDER IN AT BY FOR WITH THIS THAT ARE BE AS AN A HOW"
    " MUCH DOES DO MANY WHICH WHO WHERE WHEN WHY CAN WILL WOULD SHOULD"
    " COULD MAY MIGHT TO FROM".split()
)


def _subject_words(question: str) -> frozenset[str]:
    """Key words from the question subject — the part before 'under'/'from'/'in'."""
    q = question.upper()
    for sep in (" UNDER ", " FROM THE ", " FROM ", " IN THE "):
        if sep in q:
            q = q[: q.index(sep)]
            break
    return frozenset(re.findall(r"\w+", q)) - _STOPS


def run(state: TGState) -> TGState:
    if state.retrieval is None or not state.retrieval.candidates:
        state.draft = Draft(answer_text="No relevant documents found.", claims=[])
        return state

    top = state.retrieval.candidates[0]
    top_clause = top.clause

    # Look in the full family for the clause whose prefix best matches the
    # question subject (the thing being asked about, before "under/from/in").
    # Requires ≥2 subject-word hits to override the BM25 top candidate.
    subj = _subject_words(state.question)
    if subj and state.retrieval.family:
        best_clause, best_score = top_clause, 0
        for rc in state.retrieval.family:
            prefix = frozenset(re.findall(r"\w+", rc.clause.source_text[:150].upper())) - _STOPS
            score = len(subj & prefix)
            if score > best_score:
                best_score, best_clause = score, rc.clause
        if best_score >= 2:
            # Only override if the winning clause has substantive content after
            # its header colon/newline — not just a table artifact like "6".
            after_header = re.split(r"[:\n]", best_clause.source_text, 1)[-1].strip()
            if len(after_header) >= 20:
                top_clause = best_clause

    state.draft = Draft(
        answer_text=top_clause.source_text,
        claims=[Claim(claim_id="c1", text=top_clause.source_text, clause_ids=[top_clause.clause_id])],
    )
    return state
