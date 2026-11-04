"""Benchmark runner — `make eval`.

Reads data/benchmark/cases.jsonl, runs the pipeline on each case, and prints
the metrics table defined in §8.4 of AGENTS.md.

Exits non-zero if any tracked metric regresses vs eval/baseline_scores.json.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from eval.generate import load_cases
from truthguard.config import ensure_dirs
from truthguard.contracts import Status, User
from truthguard.pipeline.graph import ask

BASELINE_PATH = Path("eval/baseline_scores.json")

_FAKE_USERS: dict[str, User] = {
    "employee": User(user_id="u-employee", name="Demo Employee", role="employee", access_levels=["all"]),
    "admin": User(user_id="u-admin", name="Demo Admin", role="admin", access_levels=["all", "compliance"]),
}


def run_case(case: dict) -> dict:
    user = _FAKE_USERS.get(case.get("user", "employee"), _FAKE_USERS["employee"])
    as_of: date | None = None
    if case.get("as_of"):
        as_of = date.fromisoformat(case["as_of"])

    try:
        verdict = ask(case["question"], user, as_of)
        return {
            "id": case["id"],
            "expected_status": case["expected"]["status"],
            "actual_status": verdict.status.value,
            "status_correct": verdict.status.value == case["expected"]["status"],
            "shown_sources": verdict.shown_sources,
            "error": None,
        }
    except Exception as exc:
        return {
            "id": case["id"],
            "expected_status": case["expected"]["status"],
            "actual_status": "ERROR",
            "status_correct": False,
            "shown_sources": [],
            "error": str(exc),
        }


def compute_metrics(results: list[dict]) -> dict:
    total = len(results)
    if total == 0:
        return {}

    status_correct = sum(1 for r in results if r["status_correct"])

    # Correct abstention: UNRESOLVED cases
    unresolved_cases = [r for r in results if r["expected_status"] == Status.UNRESOLVED.value]
    correct_abstention = (
        sum(1 for r in unresolved_cases if r["status_correct"]) / len(unresolved_cases)
        if unresolved_cases
        else None
    )

    # Silent blends: CONFLICT_RESOLVED verdicts with < 2 shown_sources
    resolved_cases = [r for r in results if r["actual_status"] == Status.CONFLICT_RESOLVED.value]
    silent_blends = sum(1 for r in resolved_cases if len(r.get("shown_sources", [])) < 2)

    return {
        "total_cases": total,
        "status_accuracy": status_correct / total,
        "correct_abstention": correct_abstention,
        "silent_blends": silent_blends,
        "errors": sum(1 for r in results if r["error"]),
    }


def print_table(metrics: dict) -> None:
    print("\n" + "=" * 60)
    print("TruthGuard Eval Metrics")
    print("=" * 60)
    for k, v in metrics.items():
        if isinstance(v, float):
            print(f"  {k:<30} {v:.1%}")
        elif v is None:
            print(f"  {k:<30} n/a")
        else:
            print(f"  {k:<30} {v}")
    print("=" * 60 + "\n")


def check_regression(metrics: dict) -> bool:
    if not BASELINE_PATH.exists():
        # First run — save as baseline
        BASELINE_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        print("No baseline found — saved current run as baseline_scores.json")
        return False

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    regressed = False

    # Check metrics that should be >= baseline (higher is better)
    for key in ("status_accuracy", "correct_abstention"):
        bv = baseline.get(key)
        cv = metrics.get(key)
        if bv is not None and cv is not None and cv < bv - 0.01:
            print(f"REGRESSION: {key} dropped from {bv:.1%} to {cv:.1%}")
            regressed = True

    # silent_blends should stay 0
    if metrics.get("silent_blends", 0) > baseline.get("silent_blends", 0):
        print(f"REGRESSION: silent_blends increased to {metrics['silent_blends']}")
        regressed = True

    return regressed


def main() -> None:
    ensure_dirs()
    cases = load_cases()
    if not cases:
        print("No benchmark cases found. Run 'make ingest' first, then add cases to data/benchmark/cases.jsonl")
        sys.exit(0)

    print(f"Running {len(cases)} benchmark case(s)...")
    results = [run_case(c) for c in cases]

    for r in results:
        status = "OK" if r["status_correct"] else "FAIL"
        err = f" ({r['error']})" if r["error"] else ""
        print(f"  [{status}] {r['id']}: expected={r['expected_status']} actual={r['actual_status']}{err}")

    metrics = compute_metrics(results)
    print_table(metrics)

    if check_regression(metrics):
        sys.exit(1)


if __name__ == "__main__":
    main()
