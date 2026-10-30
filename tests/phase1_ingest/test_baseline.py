"""Smoke test for Phase 1 baseline."""
from __future__ import annotations

from truthguard.db.conn import get_conn
from truthguard.ingest import run


def test_ingest_txt(tmp_txt):
    path = tmp_txt("policy.txt", "Managers may approve up to $5,000. Receipts are required.")
    doc_ids = run([path])
    assert len(doc_ids) == 1
    doc_id = doc_ids[0]

    conn = get_conn()
    doc = conn.execute("SELECT doc_id, language FROM documents WHERE doc_id = ?", [doc_id]).fetchone()
    assert doc is not None

    clauses = conn.execute("SELECT source_text FROM clauses WHERE doc_id = ?", [doc_id]).fetchall()
    assert len(clauses) >= 1
    texts = [r[0] for r in clauses]
    assert any("5,000" in t for t in texts)


def test_ingest_idempotent(tmp_txt):
    path = tmp_txt("policy2.txt", "Only one sentence here.")
    doc_ids_1 = run([path])
    doc_ids_2 = run([path])
    assert doc_ids_1 == doc_ids_2

    conn = get_conn()
    count = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE doc_id = ?", [doc_ids_1[0]]
    ).fetchone()[0]
    assert count == 1


def test_ingest_empty_dir(tmp_path):
    doc_ids = run([str(tmp_path / "nonexistent.txt")])
    assert doc_ids == []
