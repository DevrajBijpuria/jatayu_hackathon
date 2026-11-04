"""EmailConnector — IMAP or Microsoft Graph Mail.Read sync.

Not tested against a real tenant/mailbox (no M365 test tenant available).
Unit tests mock the IMAP calls; see tests/phase1_ingest/test_connectors.py.
"""
from __future__ import annotations

import email
import imaplib
from pathlib import Path

from truthguard.connectors import BaseConnector

_SUPPORTED_MIME = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
_SUPPORTED_EXT = {".txt", ".pdf", ".docx", ".eml"}


class EmailConnector(BaseConnector):
    name = "email"

    def __init__(
        self,
        imap_host: str,
        imap_user: str,
        imap_password: str,
        mail_folder: str = "INBOX",
        dest_dir: str = "data/raw/email",
    ) -> None:
        self.imap_host = imap_host
        self.imap_user = imap_user
        self.imap_password = imap_password
        self.mail_folder = mail_folder
        self.dest_dir = Path(dest_dir)

    def sync(self, conn) -> list[str]:
        cursor = self._get_cursor(conn)  # last seen UID
        last_uid = int(cursor) if cursor and cursor.isdigit() else 0

        try:
            imap = imaplib.IMAP4_SSL(self.imap_host)
            imap.login(self.imap_user, self.imap_password)
            imap.select(self.mail_folder, readonly=True)
        except Exception as exc:
            self._update_state(conn, str(last_uid), f"error:connect:{exc}")
            return []

        downloaded: list[str] = []
        new_max_uid = last_uid

        try:
            search_crit = f"UID {last_uid + 1}:*" if last_uid else "ALL"
            _, data = imap.uid("search", None, search_crit)  # type: ignore[arg-type]
            uid_list = (data[0].decode().split() if data[0] else [])

            for uid_bytes in uid_list:
                uid = int(uid_bytes)
                if uid <= last_uid:
                    continue
                _, msg_data = imap.uid("fetch", str(uid), "(RFC822)")  # type: ignore[arg-type]
                if not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
                if not raw:
                    continue
                msg = email.message_from_bytes(raw)

                self.dest_dir.mkdir(parents=True, exist_ok=True)

                # Save full .eml
                eml_path = self.dest_dir / f"uid-{uid}.eml"
                eml_path.write_bytes(raw)
                downloaded.append(str(eml_path))

                # Also save recognised attachments
                if msg.is_multipart():
                    for part in msg.walk():
                        fname = part.get_filename()
                        if not fname:
                            continue
                        if Path(fname).suffix.lower() not in _SUPPORTED_EXT:
                            continue
                        payload = part.get_payload(decode=True)
                        if payload:
                            att_path = self.dest_dir / fname
                            att_path.write_bytes(payload)
                            downloaded.append(str(att_path))

                if uid > new_max_uid:
                    new_max_uid = uid
        except Exception as exc:
            self._update_state(conn, str(last_uid), f"error:fetch:{exc}")
            return []
        finally:
            try:
                imap.logout()
            except Exception:
                pass

        doc_ids: list[str] = []
        if downloaded:
            from truthguard.ingest import run as ingest_run
            try:
                doc_ids = ingest_run(downloaded)
            except Exception as exc:
                self._update_state(conn, str(new_max_uid), f"error:ingest:{exc}")
                return []

        self._update_state(conn, str(new_max_uid), "ok")
        return doc_ids
