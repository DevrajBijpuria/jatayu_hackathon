"""Phase 4 — Critic (real implementation).

Five tools + three mandatory checks (contradiction, staleness, unsupported) run
unconditionally; the LLM enriches finding detail text when an API key is set.
See AGENTS.md §6 Phase 4.
"""
from __future__ import annotations

import itertools
from datetime import date
from typing import Any

from pydantic import BaseModel

from truthguard import config
from truthguard.contracts import Finding, FindingType, TGState
from truthguard.db.conn import get_conn
from truthguard.lang import grounding_check, numbers_in_text

# ---------------------------------------------------------------------------
# NLI model (lazy-loaded; falls back to zeros when not installed)
# ---------------------------------------------------------------------------

_nli_cache: tuple | None = None  # (tokenizer, model)


def _get_nli() -> tuple:
    global _nli_cache
    if _nli_cache is None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer  # type: ignore

        tok = AutoTokenizer.from_pretrained(config.NLI_MODEL)
        mdl = AutoModelForSequenceClassification.from_pretrained(config.NLI_MODEL)
        mdl.eval()
        _nli_cache = (tok, mdl)
    return _nli_cache


# ---------------------------------------------------------------------------
# Tool 1 — compare_values
# ---------------------------------------------------------------------------

def compare_values(conn, clause_ids: list[str]) -> list[dict]:
    """Return diffs in value_num/scope/condition_text among the given clauses."""
    if len(clause_ids) < 2:
        return []
    ph = ",".join("?" * len(clause_ids))
    rows = conn.execute(
        f"SELECT clause_id, value_num, scope, condition_text FROM clauses WHERE clause_id IN ({ph})",
        clause_ids,
    ).fetchall()
    if len(rows) < 2:
        return []

    diffs = []
    for (id_a, vn_a, sc_a, ct_a), (id_b, vn_b, sc_b, ct_b) in itertools.combinations(rows, 2):
        for field, va, vb in [("value_num", vn_a, vn_b), ("scope", sc_a, sc_b), ("condition_text", ct_a, ct_b)]:
            if field == "value_num" and (va is None or vb is None):
                continue  # skip null values; staleness check covers missing data
            if va != vb and not (va is None and vb is None):
                diffs.append({"field": field, "clause_a": id_a, "value_a": va, "clause_b": id_b, "value_b": vb})
    return diffs


# ---------------------------------------------------------------------------
# Tool 2 — nli
# ---------------------------------------------------------------------------

def nli(text_a: str, text_b: str) -> dict:
    """DeBERTa NLI probabilities. Returns {contradiction, entailment, neutral}."""
    try:
        import torch  # type: ignore

        tok, mdl = _get_nli()
        inputs = tok(text_a, text_b, return_tensors="pt", truncation=True, max_length=512, padding=True)
        with torch.no_grad():
            logits = mdl(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0].tolist()
        # mDeBERTa-v3 label order from model.config.id2label
        id2label = mdl.config.id2label
        return {id2label.get(i, str(i)).lower(): float(p) for i, p in enumerate(probs)}
    except Exception:
        return {"contradiction": 0.0, "entailment": 0.0, "neutral": 1.0}


# ---------------------------------------------------------------------------
# Tool 3 — lookup_conflicts
# ---------------------------------------------------------------------------

def lookup_conflicts(conn, clause_id: str) -> list[dict]:
    """Rows from the conflicts table for this clause."""
    rows = conn.execute(
        "SELECT conflict_id, clause_a, clause_b, kind, score FROM conflicts WHERE clause_a = ? OR clause_b = ?",
        [clause_id, clause_id],
    ).fetchall()
    return [{"conflict_id": r[0], "clause_a": r[1], "clause_b": r[2], "kind": r[3], "score": r[4]} for r in rows]


# ---------------------------------------------------------------------------
# Tool 4 — find_newer
# ---------------------------------------------------------------------------

def find_newer(
    conn,
    clause_id: str,
    user_access: list[str],
    as_of: date | None,
) -> list[dict]:
    """Newer or superseding clauses accessible to the user, respecting as_of."""
    row = conn.execute(
        "SELECT concept_id, subject, scope, effective_date FROM clauses WHERE clause_id = ?",
        [clause_id],
    ).fetchone()
    if row is None:
        return []
    concept_id, subject, scope, eff_date = row

    ph = ",".join("?" * len(user_access))
    seen: set[str] = set()
    output: list[dict] = []

    def _add(rows: list) -> None:
        for r in rows:
            if r[0] not in seen and r[0] != clause_id:
                seen.add(r[0])
                output.append({
                    "clause_id": r[0],
                    "concept_id": r[1],
                    "effective_date": str(r[2]) if r[2] else None,
                    "supersedes": r[3],
                })

    # Condition 1: explicit supersession (this clause is in the supersedes column of another)
    q1 = f"SELECT clause_id, concept_id, effective_date, supersedes FROM clauses WHERE supersedes = ? AND access_level IN ({ph}) AND status = 'active'"
    a1: list[Any] = [clause_id] + user_access
    if as_of is not None:
        q1 += " AND (effective_date IS NULL OR effective_date <= ?)"
        a1.append(as_of)
    _add(conn.execute(q1, a1).fetchall())

    # Condition 2: same concept/subject/scope, later effective_date
    if concept_id is not None and eff_date is not None:
        eff_subj = subject if subject is not None else ""
        q2 = f"""SELECT clause_id, concept_id, effective_date, supersedes FROM clauses
                 WHERE concept_id = ? AND coalesce(subject, '') = ? AND scope = ?
                 AND effective_date > ? AND status = 'active' AND access_level IN ({ph})"""
        a2: list[Any] = [concept_id, eff_subj, scope, eff_date] + user_access
        if as_of is not None:
            q2 += " AND (effective_date IS NULL OR effective_date <= ?)"
            a2.append(as_of)
        _add(conn.execute(q2, a2).fetchall())

    return output


# ---------------------------------------------------------------------------
# Tool 5 — claim_supported
# ---------------------------------------------------------------------------

def claim_supported(claim_text: str, clause_id: str, conn) -> dict:
    """NLI entailment of claim given passage + number-presence check."""
    row = conn.execute("SELECT source_text FROM clauses WHERE clause_id = ?", [clause_id]).fetchone()
    if row is None:
        return {"entailment": 0.0, "number_present": False}

    passage = row[0]
    nli_result = nli(passage, claim_text)
    entailment = nli_result.get("entailment", 0.0)

    claim_nums = numbers_in_text(claim_text)
    number_present = all(grounding_check(n, passage) for n in claim_nums) if claim_nums else True

    return {"entailment": entailment, "number_present": number_present}


# ---------------------------------------------------------------------------
# Mandatory check 1 — Contradiction
# ---------------------------------------------------------------------------

def _check_contradiction(conn, state: TGState) -> list[Finding]:
    findings: list[Finding] = []
    retrieval = state.retrieval
    if retrieval is None:
        return findings

    family_ids = [rc.clause.clause_id for rc in retrieval.family]

    # compare_values on the entire family
    diffs = compare_values(conn, family_ids)
    if diffs:
        involved = list({d["clause_a"] for d in diffs} | {d["clause_b"] for d in diffs})
        detail = "; ".join(
            f"{d['clause_a']} vs {d['clause_b']}: {d['field']} differs ({d['value_a']} vs {d['value_b']})"
            for d in diffs[:3]
        )
        findings.append(Finding(
            type=FindingType.CONTRADICTION,
            claim_id=None,
            clause_ids=involved,
            detail=detail,
            evidence={"value_diffs": diffs},
        ))

    # lookup_conflicts for each cited clause
    cited_ids: set[str] = set()
    if state.draft:
        for claim in state.draft.claims:
            cited_ids.update(claim.clause_ids)

    seen_pairs: set[frozenset] = set()
    for cid in cited_ids:
        for cf in lookup_conflicts(conn, cid):
            pair: frozenset = frozenset([cf["clause_a"], cf["clause_b"]])
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                findings.append(Finding(
                    type=FindingType.CONTRADICTION,
                    claim_id=None,
                    clause_ids=[cf["clause_a"], cf["clause_b"]],
                    detail=f"Recorded conflict: {cf['kind']} (score={cf['score']:.2f})",
                    evidence={"conflict": cf},
                ))

    # NLI for qualitative pairs in the family
    qualitative = [rc.clause for rc in retrieval.family if rc.clause.clause_type == "qualitative"]
    for a, b in itertools.combinations(qualitative, 2):
        result = nli(a.source_text, b.source_text)
        score = result.get("contradiction", 0.0)
        if score >= config.NLI_CONTRADICTION_THRESHOLD:
            findings.append(Finding(
                type=FindingType.CONTRADICTION,
                claim_id=None,
                clause_ids=[a.clause_id, b.clause_id],
                detail=f"NLI contradiction {score:.2f} between {a.clause_id} and {b.clause_id}",
                evidence={"nli_contradiction": score},
            ))

    # Restricted-conflict flag — emit with no clause text
    if retrieval.restricted_conflict:
        findings.append(Finding(
            type=FindingType.CONTRADICTION,
            claim_id=None,
            clause_ids=[],
            detail="restricted source conflicts",
            evidence={},
        ))

    return findings


# ---------------------------------------------------------------------------
# Mandatory check 2 — Staleness
# ---------------------------------------------------------------------------

def _check_staleness(conn, state: TGState) -> list[Finding]:
    findings: list[Finding] = []
    if state.draft is None or state.retrieval is None:
        return findings

    cited_ids: set[str] = {cid for claim in state.draft.claims for cid in claim.clause_ids}
    family_dates = {rc.clause.clause_id: rc.clause.effective_date for rc in state.retrieval.family}
    any_family_has_date = any(d is not None for d in family_dates.values())

    for clause_id in cited_ids:
        newer = find_newer(conn, clause_id, state.user.access_levels, state.as_of)
        if newer:
            newer_ids = [n["clause_id"] for n in newer]
            findings.append(Finding(
                type=FindingType.STALE,
                claim_id=None,
                clause_ids=[clause_id] + newer_ids,
                detail=f"{clause_id} is superseded by or has a newer version: {', '.join(newer_ids)}",
                evidence={"newer_clauses": newer},
            ))
        elif family_dates.get(clause_id) is None and any_family_has_date:
            # Cited clause has no date but family has dated members → cannot confirm recency
            findings.append(Finding(
                type=FindingType.STALE,
                claim_id=None,
                clause_ids=[clause_id],
                detail=f"{clause_id} has no effective date; a dated version exists in the same family",
                evidence={"unknown_date": clause_id},
            ))

    return findings


# ---------------------------------------------------------------------------
# Mandatory check 3 — Unsupported claims
# ---------------------------------------------------------------------------

def _check_unsupported(conn, state: TGState) -> list[Finding]:
    findings: list[Finding] = []
    if state.draft is None:
        return findings

    for claim in state.draft.claims:
        if claim.text.strip().lower().startswith("not found"):
            continue
        for clause_id in claim.clause_ids:
            result = claim_supported(claim.text, clause_id, conn)
            if result["entailment"] < 0.5 or not result["number_present"]:
                reasons = []
                if result["entailment"] < 0.5:
                    reasons.append(f"entailment={result['entailment']:.2f} < 0.5")
                if not result["number_present"]:
                    reasons.append("number not in passage")
                findings.append(Finding(
                    type=FindingType.UNSUPPORTED,
                    claim_id=claim.claim_id,
                    clause_ids=[clause_id],
                    detail=f"Claim not supported by {clause_id}: {'; '.join(reasons)}",
                    evidence={"claim_supported": result},
                ))

    return findings


# ---------------------------------------------------------------------------
# LLM enrichment (optional — rewrites detail text only)
# ---------------------------------------------------------------------------

class _EnrichedDetail(BaseModel):
    finding_index: int
    detail: str


class _CriticResponse(BaseModel):
    enriched_details: list[_EnrichedDetail]


def _enrich_with_llm(state: TGState, findings: list[Finding]) -> list[Finding]:
    try:
        import truthguard.llm as llm

        findings_text = "\n".join(
            f"[{i}] {f.type.value}: clause_ids={f.clause_ids} evidence={f.evidence}"
            for i, f in enumerate(findings)
        )
        result = llm.complete(
            "critic",
            {
                "question": state.question,
                "draft_text": state.draft.answer_text if state.draft else "",
                "findings_json": findings_text,
            },
            model="large",
            json_schema=_CriticResponse,
        )
        response = _CriticResponse.model_validate(result)
        for item in response.enriched_details:
            if 0 <= item.finding_index < len(findings):
                findings[item.finding_index] = findings[item.finding_index].model_copy(
                    update={"detail": item.detail}
                )
        return findings
    except Exception:
        return findings


# ---------------------------------------------------------------------------
# Entry point (LangGraph node)
# ---------------------------------------------------------------------------

def run(state: TGState) -> TGState:
    if state.retrieval is None or state.draft is None:
        return state

    conn = get_conn()

    # Three mandatory checks — always run regardless of LLM availability
    findings: list[Finding] = []
    findings.extend(_check_contradiction(conn, state))
    findings.extend(_check_staleness(conn, state))
    findings.extend(_check_unsupported(conn, state))

    # LLM enrichment: writes better detail text; never adds/removes findings
    if config.LLM_API_KEY and findings:
        findings = _enrich_with_llm(state, findings)

    state.findings = list(state.findings) + findings
    return state
