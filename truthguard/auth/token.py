"""OIDC token verification and group → access mapping.

Used when ENABLE_SSO=true. Verifies every request's Bearer token against the
provider's JWKS endpoint and maps group claims to TruthGuard access_levels.

Requires the 'sso' optional-dependency group: pip install -e '.[sso]'
"""
from __future__ import annotations

import threading
from typing import Any

from truthguard import config
from truthguard.contracts import User

# JWKS client is cached and refreshed automatically by PyJWT
_jwks_lock = threading.Lock()
_jwks_client: Any = None  # jwt.PyJWKClient


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        with _jwks_lock:
            if _jwks_client is None:
                import jwt  # PyJWT[crypto]
                jwks_uri = config.OIDC_ISSUER.rstrip("/") + "/protocol/openid-connect/certs"
                _jwks_client = jwt.PyJWKClient(jwks_uri, cache_jwk_set=True, lifespan=360)
    return _jwks_client


def _map_groups(groups: list[str]) -> tuple[list[str], str]:
    """Return (access_levels, role) for the given IdP groups."""
    access_levels: list[str] = []
    role = "employee"
    for grp in groups:
        levels = config.GROUP_TO_ACCESS.get(grp, [])
        for lv in levels:
            if lv not in access_levels:
                access_levels.append(lv)
        if grp == config.ADMIN_GROUP:
            role = "admin"
    if not access_levels:
        access_levels = ["all"]
    return access_levels, role


def verify_token(token: str) -> User:
    """Verify a Bearer token and return the authenticated User.

    Raises jwt.InvalidTokenError subclasses on any failure.
    """
    import jwt  # PyJWT[crypto]

    client = _get_jwks_client()
    signing_key = client.get_signing_key_from_jwt(token)

    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience=config.OIDC_AUDIENCE,
        issuer=config.OIDC_ISSUER,
        options={"require": ["exp", "iat", "iss", "sub"]},
    )

    groups: list[str] = payload.get("groups", [])
    access_levels, role = _map_groups(groups)

    return User(
        user_id=payload["sub"],
        name=payload.get("name") or payload.get("preferred_username"),
        role=role,
        access_levels=access_levels,
    )
