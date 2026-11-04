"""Central configuration — all env vars and constants live here."""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")


# ── LLM ───────────────────────────────────────────────────────────────────────
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_MODEL_SMALL: str = os.getenv("LLM_MODEL_SMALL", "llama-3.1-8b-instant")
LLM_MODEL_LARGE: str = os.getenv("LLM_MODEL_LARGE", "llama-3.3-70b-versatile")

# ── ML models (optional install group) ────────────────────────────────────────
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
RERANK_MODEL: str = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
NLI_MODEL: str = os.getenv(
    "NLI_MODEL",
    "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
)

# ── Storage ───────────────────────────────────────────────────────────────────
DUCKDB_PATH: str = os.getenv("DUCKDB_PATH", "data/truthguard.duckdb")
INDEX_DIR: str = os.getenv("INDEX_DIR", "data/index")

# ── Feature flags ─────────────────────────────────────────────────────────────
ENABLE_HINDI: bool = _bool("ENABLE_HINDI", True)
ENABLE_CONNECTORS: bool = _bool("ENABLE_CONNECTORS", False)
ENABLE_SSO: bool = _bool("ENABLE_SSO", False)

# ── Connectors ────────────────────────────────────────────────────────────────
INBOX_DIR: str = os.getenv("INBOX_DIR", "data/raw/inbox")
MS_TENANT_ID: str = os.getenv("MS_TENANT_ID", "")
MS_CLIENT_ID: str = os.getenv("MS_CLIENT_ID", "")
MS_CLIENT_SECRET: str = os.getenv("MS_CLIENT_SECRET", "")
SHAREPOINT_SITE_ID: str = os.getenv("SHAREPOINT_SITE_ID", "")
SHAREPOINT_DRIVE_ID: str = os.getenv("SHAREPOINT_DRIVE_ID", "")
MAILBOX_USER: str = os.getenv("MAILBOX_USER", "circulars@example.org")
MAIL_FOLDER: str = os.getenv("MAIL_FOLDER", "Circulars")
IMAP_HOST: str = os.getenv("IMAP_HOST", "")
IMAP_USER: str = os.getenv("IMAP_USER", "")
IMAP_PASSWORD: str = os.getenv("IMAP_PASSWORD", "")
CONNECTOR_POLL_MINUTES: int = int(os.getenv("CONNECTOR_POLL_MINUTES", "15"))

# ── SSO ───────────────────────────────────────────────────────────────────────
OIDC_ISSUER: str = os.getenv("OIDC_ISSUER", "http://localhost:8080/realms/truthguard")
OIDC_CLIENT_ID: str = os.getenv("OIDC_CLIENT_ID", "truthguard-web")
OIDC_CLIENT_SECRET: str = os.getenv("OIDC_CLIENT_SECRET", "")
OIDC_AUDIENCE: str = os.getenv("OIDC_AUDIENCE", "truthguard-api")

_raw_group_map = os.getenv(
    "GROUP_TO_ACCESS",
    '{"tg-employees":["all"],"tg-compliance":["all","compliance"],"tg-board":["all","compliance","board"]}',
)
GROUP_TO_ACCESS: dict[str, list[str]] = json.loads(_raw_group_map)
ADMIN_GROUP: str = os.getenv("ADMIN_GROUP", "tg-compliance")

# ── Thresholds ────────────────────────────────────────────────────────────────
NLI_CONTRADICTION_THRESHOLD: float = 0.80
EMBED_CONCEPT_SIMILARITY_THRESHOLD: float = 0.80
SUPERSEDES_CONF_REGEX: float = 0.95
SUPERSEDES_CONF_LLM: float = 0.60
SUPERSEDES_CONF_REVIEW_THRESHOLD: float = 0.80
BM25_TOP_K: int = 30
FAISS_TOP_K: int = 30
RERANK_TOP_K: int = 5

# ── USE_BASELINE switches ─────────────────────────────────────────────────────
# Set a phase key to False once its real impl.py passes acceptance criteria.
USE_BASELINE: dict[str, bool] = {
    "ingest": _bool("BASELINE_INGEST", True),
    "retrieve": _bool("BASELINE_RETRIEVE", True),
    "synthesize": _bool("BASELINE_SYNTHESIZE", True),
    "critic": _bool("BASELINE_CRITIC", True),
    "resolve": _bool("BASELINE_RESOLVE", True),
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def ensure_dirs() -> None:
    Path(DUCKDB_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(INDEX_DIR).mkdir(parents=True, exist_ok=True)
