"""User-management API rules, against an in-memory fake of truthguard.auth.keycloak_admin.

Runs in ENABLE_SSO=false mode: X-User admin is user 'u-admin'.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from truthguard.auth import keycloak_admin as kc
from truthguard.db.conn import get_conn


class FakeKeycloak:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.groups: dict[str, set[str]] = {}
        self.passwords: dict[str, tuple[str, bool]] = {}
        self.ended: list[str] = []

    def add(self, uid, email, groups, enabled=True):
        self.users[uid] = {"id": uid, "username": email, "email": email, "firstName": email.split("@")[0],
                           "lastName": "", "enabled": enabled}
        self.groups[uid] = set(groups)

    def install(self, monkeypatch):
        def create_user(email, first, last, groups):
            if any(u["email"] == email for u in self.users.values()):
                raise kc.KeycloakError(409, "User exists with same username")
            uid = f"id-{len(self.users)}"
            self.add(uid, email, groups)
            return uid

        fns = {
            "list_users": lambda search="": [u for u in self.users.values() if search in u["email"]],
            "get_user": lambda uid: dict(self.users[uid]),
            "user_groups": lambda uid: set(self.groups[uid]),
            "group_members": lambda g: [self.users[u] for u, gs in self.groups.items() if g in gs],
            "create_user": create_user,
            "set_enabled": lambda uid, enabled: self.users[uid].update(enabled=enabled),
            "add_to_group": lambda uid, g: self.groups[uid].add(g),
            "remove_from_group": lambda uid, g: self.groups[uid].discard(g),
            "set_temporary_password": lambda uid, pw: self.passwords.__setitem__(uid, (pw, True)),
            "end_sessions": lambda uid: self.ended.append(uid),
        }
        for name, fn in fns.items():
            monkeypatch.setattr(kc, name, fn)


@pytest.fixture
def fake(monkeypatch):
    f = FakeKeycloak()
    f.add("u-admin", "admin@tg.local", ["tg-admins", "tg-compliance"])
    f.install(monkeypatch)
    return f


@pytest.fixture
def client():
    from truthguard.api.main import app
    return TestClient(app)


ADMIN = {"X-User": "admin"}


def _audit():
    return get_conn().execute(
        "SELECT action, target_id, detail, ends_sessions FROM admin_audit ORDER BY acted_at"
    ).fetchall()


def test_non_admin_gets_403(client, fake):
    assert client.get("/users", headers={"X-User": "employee"}).status_code == 403
    assert client.get("/admin-audit", headers={"X-User": "employee"}).status_code == 403


def test_create_returns_temporary_password_once_and_never_stores_it(client, fake):
    r = client.post("/users", headers=ADMIN,
                    json={"name": "Asha Rao", "email": "Asha@TG.local", "access_group": "tg-employees"})
    assert r.status_code == 201
    body = r.json()
    pw = body["temporary_password"]
    assert pw and body["user"]["access_group"] == "tg-employees" and not body["user"]["is_admin"]
    uid = body["user"]["id"]
    assert fake.passwords[uid] == (pw, True)  # temporary in Keycloak

    listed = client.get("/users", headers=ADMIN).json()
    assert all("temporary_password" not in u for u in listed)
    assert pw not in str(_audit()) and pw not in str(client.get("/admin-audit", headers=ADMIN).json())
    assert _audit()[0][0] == "create"


def test_rejects_unknown_access_level_and_duplicate_email(client, fake):
    bad = {"name": "X Y", "email": "x@tg.local", "access_group": "tg-admins"}
    assert client.post("/users", headers=ADMIN, json=bad).status_code == 422
    dup = {"name": "A", "email": "admin@tg.local", "access_group": "tg-employees"}
    assert client.post("/users", headers=ADMIN, json=dup).status_code == 409


def test_admin_cannot_disable_self_or_drop_own_admin(client, fake):
    assert client.patch("/users/u-admin", headers=ADMIN, json={"enabled": False}).status_code == 409
    assert client.patch("/users/u-admin", headers=ADMIN, json={"is_admin": False}).status_code == 409
    assert fake.users["u-admin"]["enabled"] and "tg-admins" in fake.groups["u-admin"]


def test_last_admin_cannot_be_removed_or_disabled(client, fake):
    fake.groups["u-admin"].discard("tg-admins")  # dev admin is not a Keycloak admin here
    fake.add("a2", "only-admin@tg.local", ["tg-admins", "tg-employees"])
    assert client.patch("/users/a2", headers=ADMIN, json={"is_admin": False}).status_code == 409
    assert client.patch("/users/a2", headers=ADMIN, json={"enabled": False}).status_code == 409

    fake.add("a3", "second-admin@tg.local", ["tg-admins", "tg-employees"])
    assert client.patch("/users/a2", headers=ADMIN, json={"is_admin": False}).status_code == 200
    assert fake.ended == ["a2"]


def test_access_reduction_and_disable_end_sessions_but_upgrade_does_not(client, fake):
    fake.add("e1", "e1@tg.local", ["tg-employees"])
    r = client.patch("/users/e1", headers=ADMIN, json={"access_group": "tg-compliance"})
    assert r.json()["access_group"] == "tg-compliance" and fake.ended == []

    client.patch("/users/e1", headers=ADMIN, json={"access_group": "tg-employees"})
    assert fake.ended == ["e1"]
    client.patch("/users/e1", headers=ADMIN, json={"enabled": False})
    assert fake.ended == ["e1", "e1"] and not fake.users["e1"]["enabled"]

    assert [(a[0], a[3]) for a in _audit()] == [
        ("access_change", False), ("access_change", True), ("disable", True)
    ]
    assert fake.groups["e1"] == {"tg-employees"}
