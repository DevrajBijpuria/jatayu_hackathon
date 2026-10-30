"""LangGraph pipeline wiring — START → retrieve → synthesize → critic → resolve → END.

Also the CLI entry point: python -m truthguard.pipeline.graph --question "..." --user employee
"""
from __future__ import annotations

import argparse
from datetime import date
from typing import Any

from langgraph.graph import END, START, StateGraph

import truthguard.critic as critic_phase
import truthguard.resolve as resolve_phase
import truthguard.retrieve as retrieve_phase
import truthguard.synthesize as synthesize_phase
from truthguard.contracts import TGState, User, Verdict

# ── Graph nodes ───────────────────────────────────────────────────────────────

def _node_retrieve(state: dict[str, Any]) -> dict[str, Any]:
    tg = TGState.model_validate(state)
    tg = retrieve_phase.run(tg)
    return tg.model_dump()


def _node_synthesize(state: dict[str, Any]) -> dict[str, Any]:
    tg = TGState.model_validate(state)
    tg = synthesize_phase.run(tg)
    return tg.model_dump()


def _node_critic(state: dict[str, Any]) -> dict[str, Any]:
    tg = TGState.model_validate(state)
    tg = critic_phase.run(tg)
    return tg.model_dump()


def _node_resolve(state: dict[str, Any]) -> dict[str, Any]:
    tg = TGState.model_validate(state)
    tg = resolve_phase.run(tg)
    return tg.model_dump()


def _should_skip_to_resolve(state: dict[str, Any]) -> str:
    """Skip synthesize+critic when the family is empty."""
    retrieval = state.get("retrieval")
    if retrieval and retrieval.get("family"):
        return "synthesize"
    return "resolve"


# ── Build graph ───────────────────────────────────────────────────────────────

def build_graph() -> Any:

    # LangGraph requires a TypedDict-like schema; we use a plain dict channel.
    g = StateGraph(dict)
    g.add_node("retrieve", _node_retrieve)
    g.add_node("synthesize", _node_synthesize)
    g.add_node("critic", _node_critic)
    g.add_node("resolve", _node_resolve)

    g.add_edge(START, "retrieve")
    g.add_conditional_edges("retrieve", _should_skip_to_resolve)
    g.add_edge("synthesize", "critic")
    g.add_edge("critic", "resolve")
    g.add_edge("resolve", END)

    return g.compile()


_graph = None


def get_graph() -> Any:
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def ask(question: str, user: User, as_of: date | None = None) -> Verdict:
    """Run the full pipeline and return the Verdict."""
    from truthguard.config import ensure_dirs
    ensure_dirs()

    initial_state = TGState(question=question, user=user, as_of=as_of)
    graph = get_graph()
    result = graph.invoke(initial_state.model_dump())
    final = TGState.model_validate(result)
    return final.verdict  # type: ignore[return-value]


# ── CLI ───────────────────────────────────────────────────────────────────────

_FAKE_USERS = {
    "employee": User(user_id="u-employee", name="Demo Employee", role="employee", access_levels=["all"]),
    "admin": User(user_id="u-admin", name="Demo Admin", role="admin", access_levels=["all", "compliance"]),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="TruthGuard ask CLI")
    parser.add_argument("--question", "-q", required=True)
    parser.add_argument("--user", "-u", default="employee", choices=["employee", "admin"])
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()

    as_of: date | None = None
    if args.as_of:
        as_of = date.fromisoformat(args.as_of)

    user = _FAKE_USERS[args.user]
    verdict = ask(args.question, user, as_of)

    print(f"\nStatus : {verdict.status.value}")
    print(f"Answer : {verdict.answer_text}")
    print(f"Sources: {', '.join(verdict.shown_sources) or '(none)'}")
    if verdict.decisions:
        for d in verdict.decisions:
            print(f"  Rule: {d.rule} — {d.explanation}")
    print()


if __name__ == "__main__":
    main()
