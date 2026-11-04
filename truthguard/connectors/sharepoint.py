"""SharePointConnector — Microsoft Graph delta-query sync.

Not tested against a real tenant (no M365 test tenant available).
Unit tests mock the HTTP calls; see tests/phase1_ingest/test_connectors.py.
"""
from __future__ import annotations

from pathlib import Path

from truthguard.connectors import BaseConnector

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


class SharePointConnector(BaseConnector):
    name = "sharepoint"

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        drive_id: str,
        dest_dir: str,
    ) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.drive_id = drive_id
        self.dest_dir = Path(dest_dir)

    def _get_token(self) -> str:
        import httpx  # type: ignore
        resp = httpx.post(
            _TOKEN_URL.format(tenant_id=self.tenant_id),
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def sync(self, conn) -> list[str]:
        try:
            import httpx  # type: ignore
        except ImportError:
            self._update_state(conn, "", "error:httpx_missing")
            return []

        try:
            token = self._get_token()
        except Exception as exc:
            self._update_state(conn, "", f"error:auth:{exc}")
            return []

        headers = {"Authorization": f"Bearer {token}"}
        cursor = self._get_cursor(conn)

        # Delta query: use stored delta link or start fresh
        if cursor and cursor.startswith("https://"):
            url = cursor
        else:
            url = f"{_GRAPH_BASE}/drives/{self.drive_id}/root/delta"

        downloaded: list[str] = []
        next_delta_link = cursor or ""

        try:
            while url:
                resp = httpx.get(url, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("value", []):
                    if "file" not in item:
                        continue
                    name = item.get("name", "")
                    suffix = Path(name).suffix.lower()
                    if suffix not in {".txt", ".pdf", ".docx", ".eml"}:
                        continue
                    item_id = item["id"]
                    dl_url = f"{_GRAPH_BASE}/drives/{self.drive_id}/items/{item_id}/content"
                    dl_resp = httpx.get(dl_url, headers=headers, timeout=60)
                    if dl_resp.status_code != 200:
                        continue
                    self.dest_dir.mkdir(parents=True, exist_ok=True)
                    dest = self.dest_dir / name
                    dest.write_bytes(dl_resp.content)
                    downloaded.append(str(dest))

                next_delta_link = data.get("@odata.deltaLink", next_delta_link)
                url = data.get("@odata.nextLink", "")
        except Exception as exc:
            self._update_state(conn, next_delta_link, f"error:{exc}")
            return []

        doc_ids: list[str] = []
        if downloaded:
            from truthguard.ingest import run as ingest_run
            try:
                doc_ids = ingest_run(downloaded)
            except Exception as exc:
                self._update_state(conn, next_delta_link, f"error:ingest:{exc}")
                return []

        self._update_state(conn, next_delta_link, "ok")
        return doc_ids
