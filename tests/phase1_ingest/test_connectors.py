"""Tests for Task 13: connectors (FolderConnector, SharePointConnector, EmailConnector)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ["BASELINE_INGEST"] = "false"
os.environ["ENABLE_CONNECTORS"] = "true"


# ---------------------------------------------------------------------------
# FolderConnector
# ---------------------------------------------------------------------------
class TestFolderConnector:
    def test_empty_dir_returns_empty(self, tmp_path, reset_db):
        from truthguard.connectors.folder import FolderConnector
        from truthguard.db.conn import get_conn

        conn = get_conn()
        fc = FolderConnector(watch_dir=str(tmp_path))
        ids = fc.sync(conn)
        assert ids == []

    def test_new_file_is_ingested(self, tmp_path, reset_db):
        from truthguard.connectors.folder import FolderConnector
        from truthguard.db.conn import get_conn

        f = tmp_path / "policy.txt"
        f.write_text(
            "ACME CORP\nDocument ID: FC-TEST-1\nIssuer: Finance\n"
            "Issued Date: 2024-01-01\nDocument Type: policy\n\n"
            "Manager approval limit is $5,000 per transaction.\n",
            encoding="utf-8",
        )
        conn = get_conn()
        fc = FolderConnector(watch_dir=str(tmp_path))
        ids = fc.sync(conn)
        assert len(ids) == 1
        # doc_id may be FC-TEST-1 (impl) or POLICY (baseline), both valid
        row = conn.execute("SELECT doc_id FROM documents WHERE doc_id = ?", [ids[0]]).fetchone()
        assert row is not None

    def test_idempotent_second_sync(self, tmp_path, reset_db):
        from truthguard.connectors.folder import FolderConnector
        from truthguard.db.conn import get_conn

        f = tmp_path / "policy2.txt"
        f.write_text(
            "ACME CORP\nDocument ID: FC-TEST-IDEM\nIssuer: Finance\n"
            "Issued Date: 2024-01-01\nDocument Type: policy\n\n"
            "Manager approval limit is $5,000 per transaction.\n",
            encoding="utf-8",
        )
        conn = get_conn()
        fc = FolderConnector(watch_dir=str(tmp_path))
        ids1 = fc.sync(conn)
        ids2 = fc.sync(conn)
        assert len(ids1) == 1
        # Second sync: file not changed → cursor past its mtime → nothing new
        assert len(ids2) == 0

    def test_missing_dir_records_error(self, tmp_path, reset_db):
        from truthguard.connectors.folder import FolderConnector
        from truthguard.db.conn import get_conn

        conn = get_conn()
        fc = FolderConnector(watch_dir=str(tmp_path / "nonexistent"))
        ids = fc.sync(conn)
        assert ids == []
        row = conn.execute(
            "SELECT last_status FROM connector_state WHERE connector = 'folder'"
        ).fetchone()
        assert row is not None
        assert "error" in row[0]

    def test_unsupported_extension_skipped(self, tmp_path, reset_db):
        from truthguard.connectors.folder import FolderConnector
        from truthguard.db.conn import get_conn

        (tmp_path / "file.csv").write_text("col1,col2\n1,2\n")
        conn = get_conn()
        fc = FolderConnector(watch_dir=str(tmp_path))
        ids = fc.sync(conn)
        assert ids == []


# ---------------------------------------------------------------------------
# SharePointConnector (mocked HTTP)
# ---------------------------------------------------------------------------
class TestSharePointConnector:
    def _make_connector(self, dest_dir: str):
        from truthguard.connectors.sharepoint import SharePointConnector
        return SharePointConnector(
            tenant_id="test-tenant",
            client_id="test-client",
            client_secret="test-secret",
            drive_id="test-drive",
            dest_dir=dest_dir,
        )

    def test_delta_downloads_file(self, tmp_path, reset_db):
        from truthguard.db.conn import get_conn

        dest = tmp_path / "sp"
        file_content = (
            b"TEST BANK\nDocument ID: SP-TEST-1\nIssuer: Test Bank\n"
            b"Issued Date: 2024-01-01\nDocument Type: circular\n\n"
            b"The withdrawal limit is Rs. 10,000 per week.\n"
        )
        token_resp = MagicMock(status_code=200)
        token_resp.json.return_value = {"access_token": "fake-token"}
        token_resp.raise_for_status = MagicMock()

        delta_resp = MagicMock(status_code=200)
        delta_resp.json.return_value = {
            "value": [{"id": "item1", "name": "circular.txt", "file": {}}],
            "@odata.deltaLink": "https://graph.microsoft.com/delta?token=abc",
        }
        delta_resp.raise_for_status = MagicMock()

        dl_resp = MagicMock(status_code=200)
        dl_resp.content = file_content

        conn = get_conn()
        connector = self._make_connector(str(dest))

        with patch("httpx.post", return_value=token_resp), \
             patch("httpx.get", side_effect=[delta_resp, dl_resp]):
            ids = connector.sync(conn)

        assert len(ids) == 1

    def test_auth_failure_records_error(self, tmp_path, reset_db):
        from truthguard.db.conn import get_conn

        conn = get_conn()
        connector = self._make_connector(str(tmp_path / "sp2"))

        import httpx
        err_resp = MagicMock()
        err_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=MagicMock()
        )
        with patch("httpx.post", return_value=err_resp):
            ids = connector.sync(conn)

        assert ids == []
        row = conn.execute(
            "SELECT last_status FROM connector_state WHERE connector = 'sharepoint'"
        ).fetchone()
        assert row is not None
        assert "error" in row[0]


# ---------------------------------------------------------------------------
# EmailConnector (mocked IMAP)
# ---------------------------------------------------------------------------
class TestEmailConnector:
    def _make_connector(self, dest_dir: str):
        from truthguard.connectors.email import EmailConnector
        return EmailConnector(
            imap_host="imap.example.com",
            imap_user="user@example.com",
            imap_password="secret",
            mail_folder="INBOX",
            dest_dir=dest_dir,
        )

    def test_fetches_new_message(self, tmp_path, reset_db):
        from email.mime.text import MIMEText

        from truthguard.db.conn import get_conn

        # Build a simple .eml
        msg = MIMEText(
            "TEST BANK\nDocument ID: EM-TEST-1\nIssuer: Test Bank\n"
            "Issued Date: 2024-01-01\nDocument Type: circular\n\n"
            "The withdrawal limit is Rs. 10,000 per week.\n"
        )
        msg["Subject"] = "Circular"
        msg["From"] = "bank@example.com"
        raw_bytes = msg.as_bytes()

        mock_imap = MagicMock()
        mock_imap.login.return_value = ("OK", [])
        mock_imap.select.return_value = ("OK", [])
        mock_imap.uid.side_effect = [
            ("OK", [b"1"]),
            ("OK", [(b"1 (RFC822 {%d})" % len(raw_bytes), raw_bytes)]),
        ]
        mock_imap.logout.return_value = ("BYE", [])

        conn = get_conn()
        connector = self._make_connector(str(tmp_path / "email"))

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
            ids = connector.sync(conn)

        assert len(ids) >= 1

    def test_imap_connect_failure_records_error(self, tmp_path, reset_db):
        from truthguard.db.conn import get_conn

        conn = get_conn()
        connector = self._make_connector(str(tmp_path / "email2"))

        with patch("imaplib.IMAP4_SSL", side_effect=OSError("Connection refused")):
            ids = connector.sync(conn)

        assert ids == []
        row = conn.execute(
            "SELECT last_status FROM connector_state WHERE connector = 'email'"
        ).fetchone()
        assert row is not None
        assert "error" in row[0]

    def test_idempotent_no_new_messages(self, tmp_path, reset_db):
        from truthguard.db.conn import get_conn

        mock_imap = MagicMock()
        mock_imap.login.return_value = ("OK", [])
        mock_imap.select.return_value = ("OK", [])
        mock_imap.uid.return_value = ("OK", [b""])
        mock_imap.logout.return_value = ("BYE", [])

        conn = get_conn()
        connector = self._make_connector(str(tmp_path / "email3"))

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
            ids = connector.sync(conn)

        assert ids == []
        row = conn.execute(
            "SELECT last_status FROM connector_state WHERE connector = 'email'"
        ).fetchone()
        assert row is not None
        assert row[0] == "ok"
