"""End-to-end test: ingest seed corpus, run the demo question, get a Verdict."""
from __future__ import annotations

from pathlib import Path

import pytest

from truthguard.config import ensure_dirs
from truthguard.contracts import Status, User
from truthguard.ingest import run as ingest_run
from truthguard.pipeline.graph import ask

SEED_DIR = Path("data/raw/acme")

_EMPLOYEE = User(user_id="u1", name="Test Employee", role="employee", access_levels=["all"])


@pytest.fixture(scope="module", autouse=True)
def ingest_seed():
    """Ingest the seed corpus once for this module."""
    ensure_dirs()
    paths = list(SEED_DIR.glob("*.txt"))
    assert paths, f"No seed documents found in {SEED_DIR}"
    ingest_run([str(p) for p in paths])


def test_demo_question_returns_verdict():
    verdict = ask("What is a manager's expense approval limit?", _EMPLOYEE)

    assert verdict is not None
    assert verdict.status in Status
    assert verdict.answer_text
    # With baselines, the answer may be naive but must not error
    assert verdict.shown_sources is not None


def test_verdict_has_valid_status():
    verdict = ask("What is a manager's expense approval limit?", _EMPLOYEE)
    assert verdict.status.value in {"SUPPORTED", "CONFLICT_RESOLVED", "RESOLVED_BY_SCOPE", "UNRESOLVED"}
