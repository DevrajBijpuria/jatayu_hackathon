"""Keycloak Admin REST API, called with the truthguard-admin service account.

The service account holds only realm-management roles manage-users, view-users
and query-groups (see infra/keycloak/realm.json). Request bodies may contain a
temporary password, so nothing here logs bodies.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from truthguard import config

_ADMIN_URL = config.OIDC_ISSUER.rstrip("/").replace("/realms/", "/admin/realms/", 1)
_TOKEN_URL = config.OIDC_ISSUER.rstrip("/") + "/protocol/openid-connect/token"

_lock = threading.Lock()
_token: dict[str, Any] = {"value": None, "expires": 0.0}
_group_ids: dict[str, str] = {}


class KeycloakError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _access_token() -> str:
    with _lock:
        if _token["value"] and time.time() < _token["expires"] - 30:
            return _token["value"]
        if not config.KC_ADMIN_CLIENT_SECRET:
            raise KeycloakError(503, "User management is not configured (KC_ADMIN_CLIENT_SECRET is empty).")
        try:
            r = httpx.post(
                _TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": config.KC_ADMIN_CLIENT_ID,
                    "client_secret": config.KC_ADMIN_CLIENT_SECRET,
                },
                timeout=10,
            )
        except httpx.HTTPError as exc:
            raise KeycloakError(503, f"Keycloak is unreachable ({type(exc).__name__}).") from exc
        if r.status_code != 200:
            raise KeycloakError(502, f"Keycloak rejected the service account (HTTP {r.status_code}).")
        body = r.json()
        _token["value"] = body["access_token"]
        _token["expires"] = time.time() + body.get("expires_in", 60)
        return _token["value"]


def _call(method: str, path: str, **kwargs: Any) -> httpx.Response:
    try:
        r = httpx.request(
            method,
            _ADMIN_URL + path,
            headers={"Authorization": f"Bearer {_access_token()}"},
            timeout=10,
            **kwargs,
        )
    except httpx.HTTPError as exc:
        raise KeycloakError(503, f"Keycloak is unreachable ({type(exc).__name__}).") from exc
    if r.status_code >= 400:
        try:
            msg = r.json().get("errorMessage") or r.json().get("error") or r.text
        except ValueError:
            msg = r.text
        raise KeycloakError(r.status_code, msg or f"Keycloak returned HTTP {r.status_code}.")
    return r


def group_id(name: str) -> str:
    if name not in _group_ids:
        for g in _call("GET", "/groups", params={"search": name, "briefRepresentation": "true"}).json():
            _group_ids[g["name"]] = g["id"]
        if name not in _group_ids:
            raise KeycloakError(500, f"Group '{name}' does not exist in Keycloak.")
    return _group_ids[name]


def group_members(name: str) -> list[dict[str, Any]]:
    return _call(
        "GET", f"/groups/{group_id(name)}/members", params={"max": 10000, "briefRepresentation": "true"}
    ).json()


def list_users(search: str = "") -> list[dict[str, Any]]:
    users = _call("GET", "/users", params={"search": search, "max": 1000, "briefRepresentation": "true"}).json()
    return [u for u in users if not u.get("username", "").startswith("service-account-")]


def get_user(user_id: str) -> dict[str, Any]:
    return _call("GET", f"/users/{user_id}").json()


def user_groups(user_id: str) -> set[str]:
    return {g["name"] for g in _call("GET", f"/users/{user_id}/groups").json()}


def create_user(email: str, first_name: str, last_name: str, groups: list[str]) -> str:
    r = _call(
        "POST",
        "/users",
        json={
            "username": email,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "enabled": True,
            "emailVerified": True,
            "groups": [f"/{g}" for g in groups],
        },
    )
    return r.headers["Location"].rstrip("/").rsplit("/", 1)[-1]


def set_enabled(user_id: str, enabled: bool) -> None:
    rep = get_user(user_id)  # PUT the full representation so no field is cleared
    rep["enabled"] = enabled
    _call("PUT", f"/users/{user_id}", json=rep)


def add_to_group(user_id: str, name: str) -> None:
    _call("PUT", f"/users/{user_id}/groups/{group_id(name)}")


def remove_from_group(user_id: str, name: str) -> None:
    _call("DELETE", f"/users/{user_id}/groups/{group_id(name)}")


def set_temporary_password(user_id: str, password: str) -> None:
    """Keycloak forces the user to choose a new password at next sign-in."""
    _call("PUT", f"/users/{user_id}/reset-password", json={"type": "password", "value": password, "temporary": True})


def send_password_email(user_id: str) -> None:
    """Keycloak emails the user a link to set their own password (needs realm SMTP)."""
    _call("PUT", f"/users/{user_id}/execute-actions-email", params={"lifespan": 86400}, json=["UPDATE_PASSWORD"])


def end_sessions(user_id: str) -> None:
    _call("POST", f"/users/{user_id}/logout")
