"""Phase 1 baseline — sentence splitter, no LLM, no ML models.

Splits text into sentences, stores clauses with source_text, doc_id, and
the document date inferred from the filename. No extraction, no conflict index.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

from truthguard.db.conn import get_conn


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        try:
            import pdfplumber  # type: ignore

            with pdfplumber.open(path) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except ImportError:
            return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        try:
            import docx  # type: ignore

            doc = docx.Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            return path.read_text(encoding="utf-8", errors="replace")
    return path.read_text(encoding="utf-8", errors="replace")


def _split_sentences(text: str) -> list[str]:
    # Split on sentence-ending punctuation including Hindi danda (।)
    sentences = re.split(r"(?<=[.!?।])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip()]


def _infer_date(path: Path) -> date | None:
    # Look for YYYY-MM-DD or YYYY in filename
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", path.stem)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def run(paths: list[str], access_level: str = "all") -> list[str]:
    conn = get_conn()
    doc_ids: list[str] = []

    for raw_path in paths:
        p = Path(raw_path)
        if not p.is_file():
            continue

        text = _read_text(p)
        content_hash = _sha256(text)

        # Dedupe by content hash
        existing = conn.execute(
            "SELECT doc_id FROM documents WHERE content_hash = ?", [content_hash]
        ).fetchone()
        if existing:
            doc_ids.append(existing[0])
            continue

        doc_id = p.stem.upper().replace(" ", "-").replace("_", "-")
        # Ensure uniqueness by appending a counter if needed
        base_id = doc_id
        counter = 1
        while conn.execute("SELECT 1 FROM documents WHERE doc_id = ?", [doc_id]).fetchone():
            doc_id = f"{base_id}-{counter}"
            counter += 1

        issued = _infer_date(p)

        conn.execute(
            """INSERT INTO documents
               (doc_id, title, source_path, doc_type, language, content_hash,
                issued_date, access_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [doc_id, p.stem, str(p), "policy", "en", content_hash, issued, access_level],
        )

        sentences = _split_sentences(text)
        for i, sentence in enumerate(sentences, start=1):
            clause_id = f"{doc_id}#{i}"
            conn.execute(
                """INSERT OR IGNORE INTO clauses
                   (clause_id, doc_id, section, source_text, language,
                    effective_date, access_level, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [clause_id, doc_id, str(i), sentence, "en", issued, access_level, "active"],
            )

        doc_ids.append(doc_id)

    return doc_ids
