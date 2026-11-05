"""Phase 1 real implementation -- Ingest & Conflict Index.

Tasks 1-11 per AGENTS.md section 6:
  1  parsers (PDF/DOCX/TXT/EML) + document row
  2  clause splitter (section-aware)
  3  injection guard (English regex)
  4  LLM extraction (optional, no-ops when LLM_API_KEY unset)
  5  number normaliser + grounding check (via lang/)
  6  second extraction + agreement check
  7  supersession regex + reference resolver
  8  concept vocabulary seed (~20 seeds) + word-overlap mapping
  9  FAISS + BM25 index rebuild
 10  conflict pre-index (SQL value_mismatch + optional NLI)
 11  run() entry point
"""
from __future__ import annotations

import hashlib
import json
import pickle
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from truthguard import config
from truthguard.db.conn import get_conn
from truthguard.lang import (
    detect_language,
    grounding_check,
    is_devanagari_quality_ok,
    parse_hindi_date,
)

# ---------------------------------------------------------------------------
# Lazy ML model holders
# ---------------------------------------------------------------------------
_embedder = None
_nli_pipe = None


def _get_embedder():
    global _embedder
    if _embedder is not None:
        return _embedder
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        _embedder = SentenceTransformer(config.EMBED_MODEL)
    except Exception:
        pass
    return _embedder


def _get_nli():
    global _nli_pipe
    if _nli_pipe is not None:
        return _nli_pipe
    try:
        from transformers import pipeline  # type: ignore
        _nli_pipe = pipeline(
            "text-classification",
            model=config.NLI_MODEL,
            return_all_scores=True,
            device=-1,
        )
    except Exception:
        pass
    return _nli_pipe


def _has_llm() -> bool:
    return bool(config.LLM_API_KEY)


# ---------------------------------------------------------------------------
# Task 1: Parsers
# ---------------------------------------------------------------------------

def _ocr_page(page) -> str:
    """OCR a pdfplumber page via pytesseract (graceful no-op if unavailable)."""
    try:
        import pytesseract  # type: ignore
        img = page.to_image(resolution=150).original
        return pytesseract.image_to_string(img, lang="hin+eng")
    except Exception:
        return ""


def _parse_pdf(path: Path) -> str:
    import pdfplumber  # type: ignore
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if config.ENABLE_HINDI and not is_devanagari_quality_ok(text):
                ocr_text = _ocr_page(page)
                if ocr_text.strip():
                    text = ocr_text
            pages.append(text)
    return "\n".join(pages)


def _pdf_table_clauses(path: Path, doc_id: str) -> list[dict[str, str]]:
    """One clause per table row: 'Header: value | Header: value …'

    This keeps table amounts and labels together so the LLM can read the right
    row instead of a sentence-split blob where column values bleed together.
    """
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return []
    clauses: list[dict[str, str]] = []
    try:
        with pdfplumber.open(path) as pdf:
            for pg_num, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables() or []
                for t_idx, table in enumerate(tables):
                    rows = [
                        [str(c).strip() if c else "" for c in row]
                        for row in (table or [])
                        if any(c for c in row)
                    ]
                    if not rows:
                        continue
                    # First row is header when none of its cells are purely numeric
                    first = rows[0]
                    if first and all(
                        not re.fullmatch(r"\d+\.?\d*", c) for c in first if c
                    ):
                        headers, data_rows = first, rows[1:]
                    else:
                        headers = [f"Col{i + 1}" for i in range(len(first))]
                        data_rows = rows
                    for r_idx, row in enumerate(data_rows):
                        parts = [
                            f"{h}: {v}"
                            for h, v in zip(headers, row)
                            if h and v
                        ]
                        if not parts:
                            continue
                        text = " | ".join(parts)
                        if len(text) < 15:
                            continue
                        clauses.append({
                            "clause_id": f"{doc_id}#P{pg_num}T{t_idx + 1}R{r_idx + 1}",
                            "section": f"P{pg_num}T{t_idx + 1}",
                            "source_text": text,
                        })
    except Exception:
        pass
    return clauses


def _parse_docx(path: Path) -> str:
    import docx  # type: ignore
    doc = docx.Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def _parse_eml(path: Path) -> str:
    import email
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f)
    parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                raw = part.get_payload(decode=True)
                if raw:
                    parts.append(raw.decode("utf-8", errors="replace"))
    else:
        raw = msg.get_payload(decode=True)
        if raw:
            parts.append(raw.decode("utf-8", errors="replace"))
    return "\n".join(parts)


def _read_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix in (".docx", ".doc"):
        return _parse_docx(path)
    if suffix == ".eml":
        return _parse_eml(path)
    return path.read_text(encoding="utf-8", errors="replace")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Document metadata extraction from structured header
# ---------------------------------------------------------------------------
_META_FIELDS = {
    "doc_id": re.compile(
        r"(?:Document\s+ID|Circular\s+No\.?|Ref(?:erence)?\s+No\.?|No\.)\s*:\s*(.+)",
        re.IGNORECASE,
    ),
    "issuer": re.compile(r"Issuer\s*:\s*(.+)", re.IGNORECASE),
    "issued": re.compile(
        r"(?:Issued\s+Date|Date|Dated)\s*:\s*"
        r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{1,2}\s+\w+\s+\d{4})",
        re.IGNORECASE,
    ),
    "doc_type": re.compile(r"Document\s+Type\s*:\s*(.+)", re.IGNORECASE),
    "translation_of": re.compile(r"Translation\s+Of\s*:\s*(.+)", re.IGNORECASE),
}

_DATE_FMTS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y"]


def _parse_date(s: str) -> date | None:
    if not s:
        return None
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _extract_doc_meta(path: Path, text: str) -> dict[str, Any]:
    header = text[:2000]
    meta: dict[str, Any] = {}
    for field, rx in _META_FIELDS.items():
        m = rx.search(header)
        if m:
            meta[field] = m.group(1).strip()

    if "doc_id" not in meta:
        meta["doc_id"] = path.stem.upper().replace(" ", "-").replace("_", "-")
    else:
        meta["doc_id"] = re.sub(r"[^A-Z0-9\-/]", "-", meta["doc_id"].upper()).strip("-")

    issued_str = meta.pop("issued", None)
    meta["issued_date"] = _parse_date(issued_str) if issued_str else None
    if meta["issued_date"] is None and issued_str and config.ENABLE_HINDI:
        meta["issued_date"] = parse_hindi_date(issued_str)

    if meta["issued_date"] is None:
        m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", path.stem)
        if m2:
            try:
                meta["issued_date"] = date(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
            except ValueError:
                pass

    translation_of_raw = meta.pop("translation_of", None)
    meta["translation_of"] = (
        re.sub(r"[^A-Z0-9\-/]", "-", translation_of_raw.upper()).strip("-")
        if translation_of_raw else None
    )

    meta.setdefault("issuer", None)
    meta.setdefault("doc_type", "policy")

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    meta.setdefault("title", lines[0] if lines else path.stem)

    return meta


# ---------------------------------------------------------------------------
# Task 2: Clause splitter (section-aware)
# ---------------------------------------------------------------------------
# Matches: "4.2 Manager Approval", "Q2:", "A2:", "Para 3(a)"
_SECTION_RX = re.compile(
    r"^(?P<sec>"
    r"\d{1,2}(?:\.\d{1,2}){0,3}"
    r"|Q\d{1,3}"
    r"|A\d{1,3}"
    r"|Para\s+\d+(?:\([a-z0-9]+\))?"
    r")\s*[:\.\)]*\s*(?P<title>.{0,100})$",
    re.MULTILINE | re.IGNORECASE,
)


def _split_clauses(text: str, doc_id: str) -> list[dict[str, str]]:
    headings = list(_SECTION_RX.finditer(text))
    clauses: list[dict[str, str]] = []

    if not headings:
        for i, s in enumerate(re.split(r"(?<=[.!?])\s+", text.strip()), 1):
            s = s.strip()
            if len(s) >= 15:
                clauses.append({"clause_id": f"{doc_id}#{i}", "section": str(i), "source_text": s})
        return _dedupe(clauses)

    for idx, hm in enumerate(headings):
        sec = hm.group("sec").strip()
        body_start = hm.end()
        body_end = headings[idx + 1].start() if idx + 1 < len(headings) else len(text)
        body = text[body_start:body_end].strip()

        if not body:
            title = hm.group("title").strip()
            if title and len(title) >= 15:
                clauses.append({"clause_id": f"{doc_id}#{sec}", "section": sec, "source_text": title})
            continue

        sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+", body)
            if s.strip() and len(s.strip()) >= 15
        ]
        if not sentences:
            continue
        if len(sentences) == 1:
            clauses.append({"clause_id": f"{doc_id}#{sec}", "section": sec, "source_text": sentences[0]})
        else:
            for j, sent in enumerate(sentences, 1):
                clauses.append({"clause_id": f"{doc_id}#{sec}.{j}", "section": sec, "source_text": sent})

    return _dedupe(clauses)


def _dedupe(clauses: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    out: list[dict] = []
    for c in clauses:
        base = c["clause_id"]
        counts[base] = counts.get(base, 0) + 1
        if counts[base] > 1:
            c = {**c, "clause_id": f"{base}_{counts[base]}"}
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# Task 3: Injection guard (English + Hindi)
# ---------------------------------------------------------------------------
_INJECTION_RX = re.compile(
    r"ignore\s+(all\s+)?previous\s+instructions?"
    r"|you\s+are\s+now\s+a\b"
    r"|\bsystem\s+prompt\b"
    r"|disregard\s+(all\s+)?instructions?"
    r"|forget\s+(all\s+)?previous"
    r"|do\s+not\s+follow\s+(your\s+)?previous"
    # Hindi injection patterns
    r"|पिछले\s+निर्देश(?:ों)?\s+(?:को\s+)?(?:अनदेखा|नज़रअंदाज़)\s+कर"
    r"|सभी\s+निर्देश\s+भूल\s+जाओ",
    re.IGNORECASE,
)


def _is_injected(text: str) -> bool:
    return bool(_INJECTION_RX.search(text))


# ---------------------------------------------------------------------------
# Tasks 4 & 6: LLM extraction (graceful no-op when API key unset)
# ---------------------------------------------------------------------------
class _Extraction(BaseModel):
    concept: str | None = None
    subject: str | None = None
    clause_type: str | None = None
    value_text: str | None = None
    value_num: float | None = None
    value_unit: str | None = None
    condition_text: str | None = None
    scope: str | None = None
    effective_date: str | None = None
    supersedes_ref: str | None = None
    text_en: str | None = None


def _llm_extract(
    clause_id: str,
    source_text: str,
    issuer: str | None,
    issued_date: date | None,
    doc_type: str,
) -> dict:
    if not _has_llm():
        return {}
    try:
        from truthguard.llm import complete
        result = complete(
            "extract_clause",
            {
                "clause_id": clause_id,
                "source_text": source_text,
                "issuer": issuer or "Unknown",
                "issued_date": str(issued_date) if issued_date else "Unknown",
                "doc_type": doc_type,
            },
            model="large",
            json_schema=_Extraction,
        )
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _llm_extract_check(clause_id: str, source_text: str, first: dict) -> dict:
    if not _has_llm():
        return {}
    try:
        from truthguard.llm import complete
        result = complete(
            "extract_clause_check",
            {
                "clause_id": clause_id,
                "source_text": source_text,
                "first_result": json.dumps(first),
            },
            model="large",
            json_schema=_Extraction,
        )
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Task 7: Supersession regex + reference resolver
# ---------------------------------------------------------------------------
_SUPER_PATTERNS = [
    re.compile(
        r"in\s+supersession\s+of\s+(?:section|para|clause)\s+([\d\.]+)\s+of\s+([A-Z][A-Z0-9\-/]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:supersedes?|revises?|replaces?|amends?)\s+(?:section|para|clause)\s+([\d\.]+)\s+of\s+([A-Z][A-Z0-9\-/]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"in\s+partial\s+modification\s+of\s+(?:circular|notification|master\s+circular)\s*(?:no\.?)?\s*([A-Z][A-Z0-9\-/\.]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"in\s+supersession\s+of\s+(?:circular|notification|master\s+circular)\s*(?:no\.?)?\s*([A-Z][A-Z0-9\-/\.]+)",
        re.IGNORECASE,
    ),
    # Hindi supersession patterns
    re.compile(r"(?:परिपत्र\s+)?([A-Z][A-Z0-9\-/\.]{3,})\s+के\s+अधिक्रमण\s+में"),
    re.compile(r"(?:को\s+)?प्रतिस्थापित\s+किया"),
]


def _find_supersession_refs(text: str) -> list[tuple[str, float]]:
    refs: list[tuple[str, float]] = []
    for rx in _SUPER_PATTERNS:
        for m in rx.finditer(text):
            refs.append((m.group(0), config.SUPERSEDES_CONF_REGEX))
    return refs


def _resolve_supersession(conn, clause_id: str, refs: list[tuple[str, float]]) -> None:
    for raw_ref, conf in refs:
        m_sec = re.search(
            r"(?:section|para|clause)\s+([\d\.]+)\s+of\s+([A-Z][A-Z0-9\-/]+)",
            raw_ref, re.IGNORECASE,
        )
        if m_sec:
            sec, doc = m_sec.group(1), m_sec.group(2).upper()
            row = conn.execute(
                "SELECT clause_id FROM clauses WHERE doc_id = ? AND section = ?", [doc, sec]
            ).fetchone()
            if row:
                _write_supersedes(conn, clause_id, row[0], conf)
                continue

        m_doc = re.search(r"(?:no\.?)?\s*([A-Z][A-Z0-9\-/\.]{3,})", raw_ref, re.IGNORECASE)
        if m_doc:
            doc = m_doc.group(1).upper().rstrip(".")
            row = conn.execute(
                "SELECT clause_id FROM clauses WHERE doc_id = ? LIMIT 1", [doc]
            ).fetchone()
            if row:
                _write_supersedes(conn, clause_id, row[0], conf * 0.8)


def _write_supersedes(conn, clause_id: str, target: str, conf: float) -> None:
    conn.execute(
        "UPDATE clauses SET supersedes = ?, supersedes_conf = ? WHERE clause_id = ?",
        [target, conf, clause_id],
    )
    if conf < config.SUPERSEDES_CONF_REVIEW_THRESHOLD:
        _add_review(conn, clause_id, "uncertain_supersedes")


# ---------------------------------------------------------------------------
# Task 8: Concept vocabulary seed + word-overlap mapping
# ---------------------------------------------------------------------------
_CONCEPT_SEEDS = [
    ("manager_expense_approval_limit", "Manager expense approval limit",
     "manager approval limit;approval limit;manager approval;expense limit;manager expense"),
    ("employee_self_approval_limit", "Employee self-approval limit",
     "self approval;employee approval;employee expense limit;self-approve"),
    ("director_expense_approval_limit", "Director expense approval limit",
     "director approval;director expense limit;director approval limit"),
    ("cfo_expense_approval_limit", "CFO expense approval limit",
     "cfo approval;cfo expense;chief financial officer approval"),
    ("expense_submission_deadline", "Expense submission deadline",
     "submit expense;submission deadline;expense report deadline;30 days;expense submission"),
    ("non_reimbursable_expenses", "Non-reimbursable expenses",
     "not reimbursable;non reimbursable;cannot reimburse;not eligible;expenses not covered"),
    ("reimbursement_processing_time", "Reimbursement processing time",
     "processing time;reimbursement time;payment timeline;business days"),
    ("remote_work_days", "Remote work days per week",
     "remote work;work from home;wfh;wfh days;work remotely;days at home;remote days"),
    ("paid_leave_days", "Annual paid leave days",
     "paid leave;annual leave;leave days;vacation days;leave entitlement"),
    ("kyc_cash_transaction_threshold", "KYC cash transaction reporting threshold",
     "kyc threshold;cash transaction;ctr;cash reporting;reporting threshold;pan card"),
    ("atm_cash_withdrawal_limit", "ATM or bank cash withdrawal limit",
     "cash withdrawal limit;withdrawal limit;atm limit;weekly withdrawal;cash limit"),
    ("pf_contribution_wage_ceiling", "Provident fund contribution wage ceiling",
     "pf ceiling;epf ceiling;provident fund ceiling;wage ceiling;pf contribution ceiling"),
    ("pf_employee_contribution_rate", "Employee PF contribution rate",
     "employee contribution;pf employee share;epf employee rate"),
    ("pf_employer_contribution_rate", "Employer PF contribution rate",
     "employer contribution;pf employer share;epf employer rate"),
    ("travel_expense_limit_mumbai", "Mumbai travel expense limit",
     "mumbai travel;mumbai expense;travel mumbai;location=mumbai"),
    ("travel_expense_limit", "Travel expense limit",
     "travel expense;travel limit;travel reimbursement"),
    ("receipt_requirement", "Receipt requirements for expenses",
     "receipt;receipts required;attach receipt;expense receipt"),
    ("leave_encashment", "Leave encashment rules",
     "leave encashment;encashment;carry forward"),
    ("provident_fund_withdrawal", "Provident fund withdrawal rules",
     "pf withdrawal;epf withdrawal;provident fund withdrawal"),
    ("expense_approval_process", "Expense approval process",
     "approval process;how to approve;expense management system;submit expense report"),
    ("children_appreciation_scheme", "Financial assistance or appreciation for children of staff",
     "appreciation children;children subordinate staff;children employees;meritorious children;"
     "financial assistance children;scholarship children;award children;child scheme;children scheme;"
     "children welfare;child welfare staff"),
    ("staff_welfare_scheme", "Staff welfare scheme or benefit",
     "staff welfare;employee welfare;subordinate staff;welfare scheme;welfare fund;"
     "welfare benefit;staff benefit;employee benefit scheme"),
    ("medical_reimbursement", "Medical reimbursement or medical allowance",
     "medical reimbursement;medical allowance;medical benefit;hospitalisation;hospital expense;"
     "medical claim;health benefit"),
    ("house_building_advance", "House building advance or housing loan",
     "house building advance;hba;housing loan;home loan advance"),
    ("leave_travel_concession", "Leave travel concession",
     "leave travel concession;ltc;travel concession;leave travel"),
]

_AUTHORITY_SEEDS = [
    ("Finance Department", 2),
    ("HR Helpdesk", 1),
    ("Human Resources", 1),
    ("Reserve Bank of India", 3),
    ("RBI", 3),
    ("Employees Provident Fund Organisation", 3),
    ("EPFO", 3),
    ("Board of Directors", 4),
]


def _seed_concepts(conn) -> None:
    for cid, label, synonyms in _CONCEPT_SEEDS:
        conn.execute(
            "INSERT OR IGNORE INTO concepts (concept_id, label, synonyms) VALUES (?, ?, ?)",
            [cid, label, synonyms],
        )


def _seed_authority(conn) -> None:
    if conn.execute("SELECT COUNT(*) FROM authority_config").fetchone()[0] > 0:
        return
    for issuer, rank in _AUTHORITY_SEEDS:
        conn.execute(
            "INSERT OR IGNORE INTO authority_config (issuer, authority_rank) VALUES (?, ?)",
            [issuer, rank],
        )


def _map_concept(conn, concept_text: str) -> str | None:
    if not concept_text:
        return None
    text_lower = concept_text.lower()
    rows = conn.execute("SELECT concept_id, label, synonyms FROM concepts").fetchall()

    for cid, label, synonyms in rows:
        all_terms = [label.lower()] + (synonyms or "").lower().split(";")
        for term in all_terms:
            if term and (term in text_lower or text_lower in term):
                return cid

    # Word-overlap: pick concept with >= 2 matching words
    words = set(re.findall(r"\w+", text_lower))
    best_cid, best_score = None, 1
    for cid, label, synonyms in rows:
        all_text = " ".join([label] + (synonyms or "").split(";")).lower()
        label_words = set(re.findall(r"\w+", all_text))
        score = len(words & label_words)
        if score > best_score:
            best_score, best_cid = score, cid
    if best_cid:
        return best_cid

    new_id = re.sub(r"[^a-z0-9]+", "_", text_lower).strip("_")[:50]
    if new_id:
        conn.execute(
            "INSERT OR IGNORE INTO concepts (concept_id, label, synonyms) VALUES (?, ?, ?)",
            [new_id, concept_text, ""],
        )
        _add_review(conn, None, "new_concept", item_id=f"concept-{new_id}")
        return new_id
    return None


# ---------------------------------------------------------------------------
# Review-queue helper
# ---------------------------------------------------------------------------
def _add_review(
    conn,
    clause_id: str | None,
    reason: str,
    missing_fields: str = "",
    item_id: str | None = None,
) -> None:
    iid = item_id or f"rv-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT OR IGNORE INTO review_queue (item_id, clause_id, reason, missing_fields)"
        " VALUES (?, ?, ?, ?)",
        [iid, clause_id, reason, missing_fields],
    )


# ---------------------------------------------------------------------------
# Task 9: Index rebuild (BM25 always; FAISS when sentence-transformers available)
# ---------------------------------------------------------------------------
def _rebuild_indexes(conn) -> None:
    rows = conn.execute(
        "SELECT clause_id, source_text FROM clauses WHERE status = 'active'"
    ).fetchall()
    if not rows:
        return
    ids = [r[0] for r in rows]
    texts = [r[1] for r in rows]

    idx_dir = Path(config.INDEX_DIR)
    idx_dir.mkdir(parents=True, exist_ok=True)

    try:
        from rank_bm25 import BM25Okapi  # type: ignore
        corpus = [re.findall(r"\w+", t.lower()) for t in texts]
        bm25 = BM25Okapi(corpus)
        with open(idx_dir / "bm25.pkl", "wb") as f:
            pickle.dump({"bm25": bm25, "ids": ids}, f)
    except Exception:
        pass

    embedder = _get_embedder()
    if embedder is None:
        return
    try:
        import faiss  # type: ignore
        import numpy as np  # type: ignore
        embeddings = embedder.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        idx = faiss.IndexFlatIP(embeddings.shape[1])
        idx.add(embeddings.astype(np.float32))
        faiss.write_index(idx, str(idx_dir / "faiss.index"))
        (idx_dir / "clause_ids.json").write_text(json.dumps(ids), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Task 10: Conflict pre-index
# ---------------------------------------------------------------------------
def _are_translation_partners(conn, doc_a: str, doc_b: str) -> bool:
    """True when doc_a and doc_b are mutual translation partners."""
    row = conn.execute(
        "SELECT 1 FROM documents WHERE doc_id = ? AND translation_of = ?",
        [doc_a, doc_b],
    ).fetchone()
    if row:
        return True
    row = conn.execute(
        "SELECT 1 FROM documents WHERE doc_id = ? AND translation_of = ?",
        [doc_b, doc_a],
    ).fetchone()
    return bool(row)


def _rebuild_conflict_index(conn) -> None:
    conn.execute("DELETE FROM conflicts")

    # SQL-level exclusion: skip pairs where one doc's translation_of = the other doc
    conn.execute("""
        INSERT OR IGNORE INTO conflicts
            (conflict_id, clause_a, clause_b, kind, score)
        SELECT
            a.clause_id || '|' || b.clause_id,
            a.clause_id,
            b.clause_id,
            'value_mismatch',
            1.0
        FROM clauses a
        JOIN clauses b
          ON  a.concept_id = b.concept_id
         AND  coalesce(a.subject, '') = coalesce(b.subject, '')
         AND  a.clause_id < b.clause_id
        JOIN documents da ON da.doc_id = a.doc_id
        JOIN documents db ON db.doc_id = b.doc_id
        WHERE a.status = 'active'
          AND b.status = 'active'
          AND a.value_num IS NOT NULL
          AND b.value_num IS NOT NULL
          AND a.value_num <> b.value_num
          AND NOT (coalesce(da.translation_of, '') = b.doc_id
               OR  coalesce(db.translation_of, '') = a.doc_id)
    """)

    nli = _get_nli()
    if nli is None:
        return
    pairs = conn.execute("""
        SELECT a.clause_id, a.source_text, b.clause_id, b.source_text, a.doc_id, b.doc_id
        FROM clauses a
        JOIN clauses b
          ON  a.concept_id = b.concept_id
         AND  a.clause_id < b.clause_id
         AND  a.doc_id <> b.doc_id
        JOIN documents da ON da.doc_id = a.doc_id
        JOIN documents db ON db.doc_id = b.doc_id
        WHERE a.status = 'active'
          AND b.status = 'active'
          AND a.value_num IS NULL
          AND b.value_num IS NULL
          AND NOT (coalesce(da.translation_of, '') = b.doc_id
               OR  coalesce(db.translation_of, '') = a.doc_id)
    """).fetchall()

    for a_id, a_txt, b_id, b_txt, doc_a, doc_b in pairs:
        # Python-level double-check for translation partners
        if _are_translation_partners(conn, doc_a, doc_b):
            continue
        try:
            result = nli(f"{a_txt} [SEP] {b_txt}")[0]
            scores = {r["label"]: r["score"] for r in result}
            contra = scores.get("contradiction", 0.0)
            if contra >= config.NLI_CONTRADICTION_THRESHOLD:
                conn.execute(
                    "INSERT OR IGNORE INTO conflicts"
                    " (conflict_id, clause_a, clause_b, kind, score) VALUES (?, ?, ?, 'nli_contradiction', ?)",
                    [f"{a_id}|{b_id}", a_id, b_id, contra],
                )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Bilingual document splitter (Task 12 Hindi)
# ---------------------------------------------------------------------------
_BILINGUAL_SEP = re.compile(
    r"^-{3,}\s*(?:ENGLISH\s+VERSION|हिन्दी\s+संस्करण|HINDI\s+VERSION)\s*-{3,}\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _split_bilingual(text: str) -> tuple[str, str] | None:
    """Return (english_text, hindi_text) if doc contains both language sections, else None."""
    parts = _BILINGUAL_SEP.split(text)
    if len(parts) < 3:
        return None
    # parts[0] is preamble (before first separator); content sections are parts[1:]
    sections = [p.strip() for p in parts[1:] if p.strip()]
    en_parts = [p for p in sections if not re.search(r"[ऀ-ॿ]", p)]
    hi_parts = [p for p in sections if re.search(r"[ऀ-ॿ]", p)]
    if not en_parts or not hi_parts:
        return None
    return en_parts[0], hi_parts[0]


def _unique_doc_id(conn, candidate: str) -> str:
    base_id, counter = candidate, 1
    doc_id = candidate
    while conn.execute("SELECT 1 FROM documents WHERE doc_id = ?", [doc_id]).fetchone():
        doc_id = f"{base_id}-{counter}"
        counter += 1
    return doc_id


def _process_one(
    conn,
    p: Path,
    text: str,
    access_level: str,
    doc_id_override: str | None = None,
    translation_of: str | None = None,
    force: bool = False,
) -> str | None:
    """Insert one document + its clauses. Returns doc_id or None on error."""
    content_hash = _sha256(text)
    existing = conn.execute(
        "SELECT doc_id FROM documents WHERE content_hash = ?", [content_hash]
    ).fetchone()
    if existing:
        if not force:
            return existing[0]
        # Force re-ingest: drop old clauses and document row, then re-process
        old_id = existing[0]
        conn.execute("DELETE FROM clauses WHERE doc_id = ?", [old_id])
        conn.execute("DELETE FROM documents WHERE doc_id = ?", [old_id])

    meta = _extract_doc_meta(p, text)
    lang = detect_language(text)

    doc_id = _unique_doc_id(conn, doc_id_override or meta["doc_id"])
    meta["doc_id"] = doc_id

    # Merge translation_of: explicit arg wins over header
    effective_translation_of = translation_of or meta.get("translation_of")

    if _is_injected(text):
        conn.execute(
            "INSERT INTO documents"
            " (doc_id, title, source_path, doc_type, language, content_hash,"
            "  issuer, issued_date, access_level, injection_flag, translation_of)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?)",
            [
                doc_id, meta.get("title", p.stem), str(p),
                meta.get("doc_type", "policy"), lang, content_hash,
                meta.get("issuer"), meta.get("issued_date"), access_level,
                effective_translation_of,
            ],
        )
        _add_review(conn, None, "injection_flag", item_id=f"inj-{doc_id}")
        return doc_id

    conn.execute(
        "INSERT INTO documents"
        " (doc_id, title, source_path, doc_type, language, content_hash,"
        "  issuer, issued_date, access_level, injection_flag, translation_of)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, FALSE, ?)",
        [
            doc_id, meta.get("title", p.stem), str(p),
            meta.get("doc_type", "policy"), lang, content_hash,
            meta.get("issuer"), meta.get("issued_date"), access_level,
            effective_translation_of,
        ],
    )

    if meta.get("issued_date") is None:
        _add_review(conn, None, "missing_date", missing_fields="issued_date",
                    item_id=f"md-{doc_id}")
    if not meta.get("issuer"):
        _add_review(conn, None, "missing_issuer", missing_fields="issuer",
                    item_id=f"mi-{doc_id}")

    raw_clauses = _split_clauses(text, doc_id)
    # For PDFs, also create one clause per table row so table amounts are
    # retrievable without sentence-split bleed-through.
    if p.suffix.lower() == ".pdf":
        raw_clauses.extend(_pdf_table_clauses(p, doc_id))

    for rc in raw_clauses:
        cid = rc["clause_id"]
        src = rc["source_text"]
        clause_lang = detect_language(src)

        extracted = _llm_extract(
            cid, src, meta.get("issuer"), meta.get("issued_date"), meta.get("doc_type", "policy")
        )

        value_num: float | None = extracted.get("value_num")
        eff_date_str: str | None = extracted.get("effective_date")
        extract_conf: float | None = None
        status = "active"

        if value_num is not None:
            if grounding_check(value_num, src):
                second = _llm_extract_check(cid, src, extracted)
                if second:
                    agree = (
                        second.get("value_num") == value_num
                        and second.get("effective_date") == eff_date_str
                        and second.get("scope") == extracted.get("scope")
                    )
                    extract_conf = 1.0 if agree else 0.5
                    if not agree:
                        status = "needs_review"
                        _add_review(conn, cid, "extraction_disagreement")
                else:
                    extract_conf = 1.0
            else:
                extracted2 = _llm_extract(
                    cid, src, meta.get("issuer"), meta.get("issued_date"), meta.get("doc_type", "policy")
                )
                value_num2 = extracted2.get("value_num")
                if value_num2 is not None and grounding_check(value_num2, src):
                    extracted, value_num = extracted2, value_num2
                    eff_date_str = extracted2.get("effective_date")
                    extract_conf = 1.0
                else:
                    value_num = None
                    status = "needs_review"
                    extract_conf = 0.0
                    _add_review(conn, cid, "grounding_failed")

        effective_date = _parse_date(eff_date_str) if eff_date_str else meta.get("issued_date")

        super_refs = _find_supersession_refs(src)

        concept_id = _map_concept(conn, extracted.get("concept") or "")

        issuer = extracted.get("issuer") or meta.get("issuer")
        authority_rank: int | None = None
        if issuer:
            row = conn.execute(
                "SELECT authority_rank FROM authority_config WHERE issuer = ?", [issuer]
            ).fetchone()
            if row:
                authority_rank = row[0]

        conn.execute(
            "INSERT OR IGNORE INTO clauses"
            " (clause_id, doc_id, section, source_text, language, text_en,"
            "  concept_id, subject, clause_type, value_num, value_unit, value_text,"
            "  condition_text, scope, issuer, authority_rank, effective_date,"
            "  access_level, extract_conf, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                cid, doc_id, rc["section"], src, clause_lang,
                extracted.get("text_en"),
                concept_id,
                extracted.get("subject"),
                extracted.get("clause_type"),
                value_num,
                extracted.get("value_unit"),
                extracted.get("value_text"),
                extracted.get("condition_text"),
                extracted.get("scope") or "*",
                issuer,
                authority_rank,
                effective_date,
                access_level,
                extract_conf,
                status,
            ],
        )

        _resolve_supersession(conn, cid, super_refs)

    return doc_id


# ---------------------------------------------------------------------------
# Task 11: run() -- the only public entry point
# ---------------------------------------------------------------------------
def run(paths: list[str], access_level: str = "all", force: bool = False) -> list[str]:
    """Ingest files at *paths*, populate the DB and indexes, return doc_ids."""
    from truthguard.config import ensure_dirs
    ensure_dirs()

    conn = get_conn()
    _seed_concepts(conn)
    _seed_authority(conn)

    doc_ids: list[str] = []

    for raw_path in paths:
        p = Path(raw_path)
        if not p.is_file():
            continue

        try:
            text = _read_file(p)
        except Exception as exc:
            print(f"[ingest] skipping {p.name}: {exc}")
            continue

        # Task 12: Bilingual document splitting
        if config.ENABLE_HINDI:
            bilingual = _split_bilingual(text)
        else:
            bilingual = None

        if bilingual is not None:
            en_text, hi_text = bilingual
            meta_check = _extract_doc_meta(p, text)
            base_id = meta_check["doc_id"]
            en_id = _unique_doc_id(conn, f"{base_id}-EN")
            hi_id = _unique_doc_id(conn, f"{base_id}-HI")
            d_en = _process_one(conn, p, en_text, access_level, doc_id_override=en_id,
                                translation_of=hi_id, force=force)
            d_hi = _process_one(conn, p, hi_text, access_level, doc_id_override=hi_id,
                                translation_of=en_id, force=force)
            for d in (d_en, d_hi):
                if d:
                    doc_ids.append(d)
        else:
            d = _process_one(conn, p, text, access_level, force=force)
            if d:
                doc_ids.append(d)

    # Tasks 9-10: Rebuild indexes after all docs ingested
    _rebuild_indexes(conn)
    _rebuild_conflict_index(conn)

    return doc_ids
