"""The admin_audit table: who changed which user, what changed, when. Never a password.

sessions_ended_at runs on every authenticated request from FastAPI's thread pool, so
each call takes its own cursor: one DuckDB connection is not safe across threads.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from truthguard.db.conn import get_conn


def record(
    actor_id: str,
    actor_name: str | None,
    target_id: str,
    target_email: str | None,
    action: str,
    detail: dict[str, Any],
    ends_sessions: bool = False,
) -> None:
    get_conn().cursor().execute(
        "INSERT INTO admin_audit (audit_id, acted_at, actor_id, actor_name, target_id, "
        "target_email, action, detail, ends_sessions) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            uuid.uuid4().hex,
            datetime.now(UTC).replace(tzinfo=None),
            actor_id,
            actor_name,
            target_id,
            target_email,
            action,
            json.dumps(detail),
            ends_sessions,
        ],
    )


def recent(limit: int = 200) -> list[dict[str, Any]]:
    rows = get_conn().cursor().execute(
        "SELECT audit_id, acted_at, actor_id, actor_name, target_id, target_email, action, "
        "detail, ends_sessions FROM admin_audit ORDER BY acted_at DESC LIMIT ?",
        [limit],
    ).fetchall()
    return [
        {
            "audit_id": r[0],
            "acted_at": r[1].isoformat() + "Z",
            "actor_id": r[2],
            "actor_name": r[3],
            "target_id": r[4],
            "target_email": r[5],
            "action": r[6],
            "detail": json.loads(r[7] or "{}"),
            "ends_sessions": r[8],
        }
        for r in rows
    ]


def sessions_ended_at(user_id: str) -> float | None:
    """Epoch seconds of the last admin action that ended this user's sessions."""
    row = get_conn().cursor().execute(
        "SELECT epoch(max(acted_at)) FROM admin_audit WHERE target_id = ? AND ends_sessions",
        [user_id],
    ).fetchone()
    return row[0] if row else None
