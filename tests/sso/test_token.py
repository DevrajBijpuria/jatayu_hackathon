"""Tests for JWT token verification and group-to-access mapping (Phase 5 SSO).

Uses unittest.mock to avoid a live Keycloak instance.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from truthguard.auth.token import _map_groups, verify_token
from truthguard.contracts import User

# ── _map_groups ──────────────────────────────────────────────────────────────

class TestMapGroups:
    def test_employee_group(self):
        levels, role = _map_groups(["tg-employees"])
        assert levels == ["all"]
        assert role == "employee"

    def test_compliance_group(self):
        levels, role = _map_groups(["tg-compliance"])
        assert set(levels) == {"all", "compliance"}
        assert role == "admin"

    def test_board_group(self):
        levels, role = _map_groups(["tg-board"])
        assert set(levels) == {"all", "compliance", "board"}
        assert role == "employee"  # ADMIN_GROUP is tg-compliance, not tg-board

    def test_no_groups_defaults_to_all(self):
        levels, role = _map_groups([])
        assert levels == ["all"]
        assert role == "employee"

    def test_duplicate_levels_deduped(self):
        # employee + board both grant "all"; should not duplicate
        levels, _ = _map_groups(["tg-employees", "tg-board"])
        assert levels.count("all") == 1


# ── verify_token (mocked JWKS) ────────────────────────────────────────────────

def _make_payload(
    *,
    sub: str = "user-123",
    name: str = "Test User",
    groups: list[str] | None = None,
    exp_offset: int = 300,
    iss: str = "http://localhost:8080/realms/truthguard",
    aud: str = "truthguard-api",
) -> dict:
    now = int(time.time())
    return {
        "sub": sub,
        "name": name,
        "groups": groups or [],
        "iat": now,
        "exp": now + exp_offset,
        "iss": iss,
        "aud": aud,
    }


def _mock_jwt_decode(payload: dict):
    """Return a mock of jwt.decode that ignores sig and returns payload."""
    mock = MagicMock()
    mock.return_value = payload
    return mock


class TestVerifyToken:
    def _patch_jwks(self, payload: dict):
        """Context manager that patches PyJWKClient and jwt.decode."""
        import jwt as pyjwt  # noqa: F401 — ensure importable

        signing_key_mock = MagicMock()
        signing_key_mock.key = "fake-key"

        jwks_mock = MagicMock()
        jwks_mock.get_signing_key_from_jwt.return_value = signing_key_mock

        return (
            patch("truthguard.auth.token._jwks_client", jwks_mock),
            patch("jwt.decode", _mock_jwt_decode(payload)),
        )

    def test_valid_employee_token(self):
        payload = _make_payload(groups=["tg-employees"])
        cm1, cm2 = self._patch_jwks(payload)
        with cm1, cm2:
            user = verify_token("fake.token.here")
        assert isinstance(user, User)
        assert user.role == "employee"
        assert user.access_levels == ["all"]
        assert user.user_id == "user-123"

    def test_valid_compliance_token(self):
        payload = _make_payload(sub="admin-456", groups=["tg-compliance"])
        cm1, cm2 = self._patch_jwks(payload)
        with cm1, cm2:
            user = verify_token("fake.token.here")
        assert user.role == "admin"
        assert "compliance" in user.access_levels

    def test_expired_token_raises(self):
        import jwt as pyjwt

        signing_key_mock = MagicMock()
        signing_key_mock.key = "fake-key"
        jwks_mock = MagicMock()
        jwks_mock.get_signing_key_from_jwt.return_value = signing_key_mock

        def raise_expired(*a, **kw):
            raise pyjwt.ExpiredSignatureError("Token is expired")

        with patch("truthguard.auth.token._jwks_client", jwks_mock):
            with patch("jwt.decode", raise_expired):
                with pytest.raises(pyjwt.ExpiredSignatureError):
                    verify_token("expired.token")

    def test_wrong_audience_raises(self):
        import jwt as pyjwt

        signing_key_mock = MagicMock()
        signing_key_mock.key = "fake-key"
        jwks_mock = MagicMock()
        jwks_mock.get_signing_key_from_jwt.return_value = signing_key_mock

        def raise_invalid(*a, **kw):
            raise pyjwt.InvalidAudienceError("Audience mismatch")

        with patch("truthguard.auth.token._jwks_client", jwks_mock):
            with patch("jwt.decode", raise_invalid):
                with pytest.raises(pyjwt.InvalidAudienceError):
                    verify_token("wrong.aud.token")

    def test_wrong_issuer_raises(self):
        import jwt as pyjwt

        signing_key_mock = MagicMock()
        signing_key_mock.key = "fake-key"
        jwks_mock = MagicMock()
        jwks_mock.get_signing_key_from_jwt.return_value = signing_key_mock

        def raise_invalid(*a, **kw):
            raise pyjwt.InvalidIssuerError("Issuer mismatch")

        with patch("truthguard.auth.token._jwks_client", jwks_mock):
            with patch("jwt.decode", raise_invalid):
                with pytest.raises(pyjwt.InvalidIssuerError):
                    verify_token("wrong.iss.token")


# ── Integration: employee cannot see compliance-only clause ──────────────────

class TestEmployeeCannotSeeComplianceClause:
    """Verify that the /ask endpoint filters compliance-only clauses for employees."""

    def test_employee_does_not_receive_compliance_clause(self):
        from fastapi.testclient import TestClient

        from truthguard.api.main import app
        from truthguard.db.conn import get_conn, reset_conn

        reset_conn()
        conn = get_conn()

        # Parent documents required by FK
        conn.execute("""
            INSERT INTO documents (doc_id, title, access_level)
            VALUES ('doc-e', 'Employee Circular', 'all'),
                   ('doc-c', 'Compliance Circular', 'compliance')
        """)
        # Insert a compliance-only clause and a universally-accessible one
        conn.execute("""
            INSERT INTO clauses (clause_id, doc_id, concept_id, source_text,
                                 access_level, effective_date, authority_rank)
            VALUES
              ('C-EMP', 'doc-e', 'loan_ltv', 'Max LTV 80% for all borrowers.',
               'all', '2024-01-01', 1),
              ('C-COMP', 'doc-c', 'loan_ltv', 'Compliance override: Max LTV 60%.',
               'compliance', '2024-01-01', 2)
        """)

        client = TestClient(app)
        response = client.post(
            "/ask",
            json={"question": "What is the LTV limit?"},
            headers={"X-User": "employee"},
        )
        assert response.status_code == 200
        data = response.json()
        shown = [s["clause_id"] for s in data["shown_sources"]]
        assert "C-COMP" not in shown, "Employee should not see compliance-only clause"

        reset_conn()
