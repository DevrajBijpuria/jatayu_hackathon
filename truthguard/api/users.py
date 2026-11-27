"""Admin-only user management: Keycloak is the user store, admin_audit records every change.

Each user is in exactly one access group (a key of GROUP_TO_ACCESS); admin rights are
the separate ADMIN_GROUP. Passwords are never stored or logged: a temporary password
is generated, set in Keycloak as temporary, and returned once in the response.
"""
from __future__ import annotations

import re
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from truthguard import config
from truthguard.auth import admin_audit
from truthguard.auth import keycloak_admin as kc
from truthguard.contracts import User

ACCESS_GROUPS = list(config.GROUP_TO_ACCESS)
_EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def build_router(require_admin: Any) -> APIRouter:
    """require_admin is main.py's dependency: 401 without a valid token, 403 for non-admins."""
    router = APIRouter()

    @router.get("/users")
    def list_users(search: str = "", admin: User = Depends(require_admin)) -> list[dict[str, Any]]:
        access_of, admins = _memberships()
        users = [_view(u, access_of, admins) for u in kc.list_users(search.strip())]
        return sorted(users, key=lambda u: u["name"].lower())

    @router.post("/users", status_code=201)
    def create_user(body: NewUser, admin: User = Depends(require_admin)) -> dict[str, Any]:
        name, email = body.name.strip(), body.email.strip().lower()
        if not name or len(name) > 100:
            raise HTTPException(status_code=422, detail="Enter the person's name.")
        if not _EMAIL_RX.match(email):
            raise HTTPException(status_code=422, detail="Enter a valid email address.")
        _check_access_group(body.access_group)

        first, _, last = name.partition(" ")
        user_id = kc.create_user(email, first, last.strip(), [body.access_group])
        temp_password, email_sent = _issue_password(user_id)
        admin_audit.record(
            admin.user_id, admin.name, user_id, email, "create",
            {"name": name, "access_group": body.access_group,
             "password_setup": "email" if email_sent else "temporary_password"},
        )
        access_of, admins = _memberships()
        return {
            "user": _view(kc.get_user(user_id), access_of, admins),
            "temporary_password": temp_password,
            "email_sent": email_sent,
        }

    @router.patch("/users/{user_id}")
    def change_user(user_id: str, body: UserChange, admin: User = Depends(require_admin)) -> dict[str, Any]:
        target = kc.get_user(user_id)
        groups = kc.user_groups(user_id)
        email = target.get("email") or target.get("username")
        is_self = user_id == admin.user_id
        is_admin_now = config.ADMIN_GROUP in groups

        if body.enabled is False and is_self:
            raise HTTPException(status_code=409, detail="You cannot disable your own account.")
        if body.is_admin is False and is_self and is_admin_now:
            raise HTTPException(status_code=409, detail="You cannot remove your own admin rights.")
        loses_admin = is_admin_now and target["enabled"] and (body.is_admin is False or body.enabled is False)
        if loses_admin:
            other_admins = [m for m in kc.group_members(config.ADMIN_GROUP) if m["enabled"] and m["id"] != user_id]
            if not other_admins:
                raise HTTPException(
                    status_code=409, detail="This is the last admin. Make someone else an admin first."
                )

        end_sessions = False
        if body.access_group is not None:
            _check_access_group(body.access_group)
            old = sorted(groups & set(ACCESS_GROUPS))
            if old != [body.access_group]:
                kc.add_to_group(user_id, body.access_group)
                for g in old:
                    if g != body.access_group:
                        kc.remove_from_group(user_id, g)
                old_levels = {lv for g in old for lv in config.GROUP_TO_ACCESS[g]}
                reduced = not old_levels <= set(config.GROUP_TO_ACCESS[body.access_group])
                end_sessions |= reduced
                admin_audit.record(
                    admin.user_id, admin.name, user_id, email, "access_change",
                    {"from": old[0] if len(old) == 1 else old or None, "to": body.access_group},
                    ends_sessions=reduced,
                )
        if body.is_admin is not None and body.is_admin != is_admin_now:
            if body.is_admin:
                kc.add_to_group(user_id, config.ADMIN_GROUP)
            else:
                kc.remove_from_group(user_id, config.ADMIN_GROUP)
                end_sessions = True
            admin_audit.record(
                admin.user_id, admin.name, user_id, email,
                "admin_grant" if body.is_admin else "admin_revoke", {},
                ends_sessions=not body.is_admin,
            )
        if body.enabled is not None and body.enabled != target["enabled"]:
            kc.set_enabled(user_id, body.enabled)
            end_sessions |= not body.enabled
            admin_audit.record(
                admin.user_id, admin.name, user_id, email,
                "enable" if body.enabled else "disable", {},
                ends_sessions=not body.enabled,
            )
        if end_sessions:
            kc.end_sessions(user_id)

        access_of, admins = _memberships()
        return _view(kc.get_user(user_id), access_of, admins)

    @router.post("/users/{user_id}/reset-password")
    def reset_password(user_id: str, admin: User = Depends(require_admin)) -> dict[str, Any]:
        target = kc.get_user(user_id)
        temp_password, email_sent = _issue_password(user_id)
        admin_audit.record(
            admin.user_id, admin.name, user_id, target.get("email") or target.get("username"),
            "password_reset", {"method": "email" if email_sent else "temporary_password"},
        )
        return {"temporary_password": temp_password, "email_sent": email_sent}

    @router.get("/admin-audit")
    def audit(limit: int = 200, admin: User = Depends(require_admin)) -> list[dict[str, Any]]:
        return admin_audit.recent(min(max(limit, 1), 1000))

    return router


class NewUser(BaseModel):
    name: str
    email: str
    access_group: str


class UserChange(BaseModel):
    access_group: str | None = None
    is_admin: bool | None = None
    enabled: bool | None = None


def _check_access_group(group: str) -> None:
    if group not in ACCESS_GROUPS:
        raise HTTPException(status_code=422, detail=f"Access level must be one of: {', '.join(ACCESS_GROUPS)}.")


def _issue_password(user_id: str) -> tuple[str | None, bool]:
    """Email a set-password link if SMTP is set up, else return a one-time temporary password."""
    if config.SEND_PASSWORD_EMAIL:
        kc.send_password_email(user_id)
        return None, True
    password = secrets.token_urlsafe(12)
    kc.set_temporary_password(user_id, password)
    return password, False


def _memberships() -> tuple[dict[str, str], set[str]]:
    access_of: dict[str, str] = {}
    for g in ACCESS_GROUPS:
        for m in kc.group_members(g):
            access_of.setdefault(m["id"], g)
    admins = {m["id"] for m in kc.group_members(config.ADMIN_GROUP)}
    return access_of, admins


def _view(u: dict[str, Any], access_of: dict[str, str], admins: set[str]) -> dict[str, Any]:
    name = " ".join(p for p in (u.get("firstName"), u.get("lastName")) if p)
    return {
        "id": u["id"],
        "email": u.get("email") or u.get("username"),
        "name": name or u.get("username"),
        "access_group": access_of.get(u["id"]),
        "is_admin": u["id"] in admins,
        "enabled": u.get("enabled", False),
        "created_at": u.get("createdTimestamp"),
    }
