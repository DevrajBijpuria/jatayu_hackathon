"""FastAPI application — see §5.4 of AGENTS.md.

ENABLE_SSO=false mode: X-User header with 'employee' or 'admin'.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile
from pydantic import BaseModel

from truthguard import config
from truthguard.contracts import User, Verdict
from truthguard.db.conn import get_conn

app = FastAPI(title="TruthGuard API", version="0.1.0")

# ── Auth ─────────────────────────────────────────────────────────────────────

_FAKE_USERS: dict[str, User] = {
    "employee": User(
        user_id="u-employee",
        name="Demo Employee",
        role="employee",
        access_levels=["all"],
    ),
    "admin": User(
        user_id="u-admin",
        name="Demo Admin",
        role="admin",
        access_levels=["all", "compliance"],
    ),
}


def get_current_user(x_user: str | None = Header(default=None)) -> User:
    if config.ENABLE_SSO:
        raise HTTPException(status_code=501, detail="SSO auth not yet implemented.")

    if os.getenv("ENV") == "production":
        raise HTTPException(
            status_code=500,
            detail="ENABLE_SSO=false is not allowed in production.",
        )

    key = (x_user or "employee").lower()
    if key not in _FAKE_USERS:
        raise HTTPException(status_code=401, detail="Unknown X-User value. Use 'employee' or 'admin'.")
    return _FAKE_USERS[key]


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


# ── Request / response models ─────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    as_of: date | None = None


class AskResponse(BaseModel):
    verdict: Verdict
    shown_sources: list[dict[str, Any]] = []


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/me")
def me(user: User = Depends(get_current_user)) -> User:
    return user


@app.post("/ask")
def ask(body: AskRequest, user: User = Depends(get_current_user)) -> AskResponse:
    from truthguard.config import ensure_dirs
    ensure_dirs()

    from truthguard.pipeline.graph import ask as _ask
    verdict = _ask(body.question, user, body.as_of)

    # Fetch source texts for the shown sources
    conn = get_conn()
    sources: list[dict[str, Any]] = []
    for clause_id in verdict.shown_sources:
        row = conn.execute(
            "SELECT clause_id, source_text, doc_id, effective_date FROM clauses WHERE clause_id = ?",
            [clause_id],
        ).fetchone()
        if row:
            sources.append(
                {"clause_id": row[0], "source_text": row[1], "doc_id": row[2], "effective_date": str(row[3])}
            )

    return AskResponse(verdict=verdict, shown_sources=sources)


@app.post("/ingest")
def ingest(
    files: list[UploadFile],
    access_level: str = "all",
    user: User = Depends(require_admin),
) -> dict[str, list[str]]:
    import tempfile
    from pathlib import Path

    import truthguard.ingest as ingest_phase

    paths: list[str] = []
    tmp_dir = tempfile.mkdtemp()
    for f in files:
        dest = Path(tmp_dir) / (f.filename or "upload")
        dest.write_bytes(f.file.read())
        paths.append(str(dest))

    doc_ids = ingest_phase.run(paths, access_level)
    return {"doc_ids": doc_ids}


@app.get("/conflicts")
def list_conflicts(
    concept_id: str | None = None,
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    conn = get_conn()
    query = """
        SELECT cf.conflict_id, cf.clause_a, cf.clause_b, cf.kind, cf.score,
               ca.source_text, cb.source_text, ca.access_level, cb.access_level
        FROM conflicts cf
        JOIN clauses ca ON ca.clause_id = cf.clause_a
        JOIN clauses cb ON cb.clause_id = cf.clause_b
        WHERE ca.access_level IN ({p})
          AND cb.access_level IN ({p})
    """.format(p=",".join("?" * len(user.access_levels)))

    params = user.access_levels + user.access_levels
    if concept_id:
        query += " AND ca.concept_id = ?"
        params.append(concept_id)

    rows = conn.execute(query, params).fetchall()
    return [
        {
            "conflict_id": r[0],
            "clause_a": r[1],
            "clause_b": r[2],
            "kind": r[3],
            "score": r[4],
            "source_a": r[5],
            "source_b": r[6],
        }
        for r in rows
    ]


@app.get("/review")
def review_queue(user: User = Depends(require_admin)) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT item_id, clause_id, reason, missing_fields, created_at FROM review_queue WHERE resolved_at IS NULL"
    ).fetchall()
    return [
        {"item_id": r[0], "clause_id": r[1], "reason": r[2], "missing_fields": r[3], "created_at": str(r[4])}
        for r in rows
    ]


@app.post("/review/{item_id}")
def resolve_review_item(
    item_id: str,
    body: dict[str, Any],
    user: User = Depends(require_admin),
) -> dict[str, str]:
    # TODO(phase5): real implementation — update clause fields, re-run conflict check
    raise HTTPException(status_code=501, detail="Review resolution belongs to Phase 5.")


@app.get("/audit/{log_id}")
def audit_entry(log_id: str, user: User = Depends(get_current_user)) -> dict[str, Any]:
    conn = get_conn()
    row = conn.execute(
        "SELECT log_id, user_id, question, as_of, status, answer, trace_json, asked_at FROM audit_log WHERE log_id = ?",
        [log_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Log entry not found.")
    if user.role != "admin" and row[1] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied.")
    return {
        "log_id": row[0],
        "user_id": row[1],
        "question": row[2],
        "as_of": str(row[3]),
        "status": row[4],
        "answer": row[5],
        "asked_at": str(row[7]),
    }


@app.post("/connectors/{name}/sync")
def connector_sync(name: str, user: User = Depends(require_admin)) -> dict[str, str]:
    if not config.ENABLE_CONNECTORS:
        raise HTTPException(status_code=501, detail="Connectors are disabled (ENABLE_CONNECTORS=false).")
    # TODO(phase1): real connector sync
    return {"status": "not_implemented"}


@app.get("/connectors")
def connector_status(user: User = Depends(require_admin)) -> list[dict[str, Any]]:
    if not config.ENABLE_CONNECTORS:
        raise HTTPException(status_code=501, detail="Connectors are disabled (ENABLE_CONNECTORS=false).")
    conn = get_conn()
    rows = conn.execute(
        "SELECT connector, cursor, last_run_at, last_status FROM connector_state"
    ).fetchall()
    return [
        {"connector": r[0], "cursor": r[1], "last_run_at": str(r[2]), "last_status": r[3]}
        for r in rows
    ]
