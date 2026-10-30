"""Benchmark generator stub — see §8.1 of AGENTS.md.

Reads and writes the §8.2 case format (data/benchmark/cases.jsonl).
The three hand-written seed cases are in data/benchmark/cases.jsonl.

TODO(phase5/eval): implement mutation-based generation for the full 200+ case set.
"""
from __future__ import annotations

import json
from pathlib import Path

CASES_PATH = Path("data/benchmark/cases.jsonl")


def load_cases() -> list[dict]:
    if not CASES_PATH.exists():
        return []
    return [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_cases(cases: list[dict]) -> None:
    CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CASES_PATH.write_text(
        "\n".join(json.dumps(c) for c in cases) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    # Stub: just print the hand-written cases
    cases = load_cases()
    print(f"Loaded {len(cases)} benchmark case(s) from {CASES_PATH}")
    for c in cases:
        print(f"  {c['id']} ({c['type']}): {c['question']!r}")


if __name__ == "__main__":
    main()
