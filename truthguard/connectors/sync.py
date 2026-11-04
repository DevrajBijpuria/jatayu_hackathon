"""Connector sync entry point — `make sync` or `python -m truthguard.connectors.sync`."""
from __future__ import annotations

from truthguard import config
from truthguard.db.conn import get_conn


def main() -> None:
    if not config.ENABLE_CONNECTORS:
        print("ENABLE_CONNECTORS=false — connectors are disabled.")
        return

    from truthguard.connectors.email import EmailConnector
    from truthguard.connectors.folder import FolderConnector
    from truthguard.connectors.sharepoint import SharePointConnector

    conn = get_conn()
    connectors = [FolderConnector()]

    if config.MS_TENANT_ID and config.MS_CLIENT_ID and config.MS_CLIENT_SECRET and config.SHAREPOINT_DRIVE_ID:
        connectors.append(
            SharePointConnector(
                tenant_id=config.MS_TENANT_ID,
                client_id=config.MS_CLIENT_ID,
                client_secret=config.MS_CLIENT_SECRET,
                drive_id=config.SHAREPOINT_DRIVE_ID,
                dest_dir="data/raw/sharepoint",
            )
        )

    if config.IMAP_HOST and config.IMAP_USER and config.IMAP_PASSWORD:
        connectors.append(
            EmailConnector(
                imap_host=config.IMAP_HOST,
                imap_user=config.IMAP_USER,
                imap_password=config.IMAP_PASSWORD,
                mail_folder=config.MAIL_FOLDER or "INBOX",
            )
        )

    for c in connectors:
        print(f"[sync] running {c.name}...")
        try:
            ids = c.sync(conn)
            print(f"[sync] {c.name}: ingested {len(ids)} doc(s)")
        except Exception as exc:
            print(f"[sync] {c.name}: error — {exc}")


if __name__ == "__main__":
    main()
