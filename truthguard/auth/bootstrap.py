"""make bootstrap-admin — create the first admin from BOOTSTRAP_ADMIN_EMAIL.

Prints a one-time temporary password (Keycloak forces a change at first sign-in).
Refuses to run if any admin already exists. Run it while the API is stopped:
DuckDB allows one writer, and the action is recorded in admin_audit.
"""
from __future__ import annotations

import secrets
import sys

import duckdb

from truthguard import config
from truthguard.auth import admin_audit
from truthguard.auth import keycloak_admin as kc
from truthguard.db.conn import get_conn

# The first admin is the compliance admin, so they can read compliance documents too.
_FIRST_ADMIN_ACCESS_GROUP = "tg-compliance"


def main() -> int:
    email = config.BOOTSTRAP_ADMIN_EMAIL.strip().lower()
    if not email:
        print("Set BOOTSTRAP_ADMIN_EMAIL in .env first.")
        return 2
    try:
        get_conn()  # fail before touching Keycloak if the API holds the database
    except duckdb.IOException:
        print("The database is in use. Stop the API, run this again, then restart the API.")
        return 1

    try:
        admins = kc.group_members(config.ADMIN_GROUP)
        if admins:
            who = ", ".join(a.get("email") or a.get("username", "?") for a in admins)
            print(f"Refusing to run: an admin already exists ({who}). Manage users on the Users screen.")
            return 1
        first, _, last = config.BOOTSTRAP_ADMIN_NAME.strip().partition(" ")
        user_id = kc.create_user(email, first, last.strip(), [_FIRST_ADMIN_ACCESS_GROUP, config.ADMIN_GROUP])
        password = secrets.token_urlsafe(12)
        kc.set_temporary_password(user_id, password)
    except kc.KeycloakError as exc:
        print(f"Keycloak error ({exc.status}): {exc.message}")
        return 1

    admin_audit.record(
        "bootstrap", "make bootstrap-admin", user_id, email, "create",
        {"name": config.BOOTSTRAP_ADMIN_NAME, "access_group": _FIRST_ADMIN_ACCESS_GROUP,
         "is_admin": True, "password_setup": "temporary_password"},
    )
    print(f"Created the first admin: {email}")
    print(f"Temporary password (shown once): {password}")
    print("Sign in at http://localhost:3000 — Keycloak will ask for a new password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
