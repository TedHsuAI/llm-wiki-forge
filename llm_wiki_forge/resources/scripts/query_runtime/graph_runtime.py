from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .challenge import challenge_query_run
from .community_nav import find_community_hits
from .io import load_communities, load_modules, load_symbols
from .models import ModuleHit, QueryRun
from .planner import plan_extraction
from .query import find_symbol_hints, print_summary, run_extraction, save_query_run
from .router import route_modules
from .semantic import evidence_sufficiency, semantic_intake, semantic_route_explanation


class QueryGraphState(TypedDict, total=False):
    wiki_root: Path
    question: str
    top: int
    extract: bool
    extract_limit: int
    modules: list[dict[str, Any]]
    symbols: list[dict[str, Any]]
    communities: list[dict[str, Any]]
    selected_modules: list[ModuleHit]
    rejected_modules: list[ModuleHit]
    tokens: list[str]
    semantic_intake: dict[str, Any]
    semantic_route: dict[str, Any]
    evidence_sufficiency: dict[str, Any]
    symbol_hints: list[dict[str, Any]]
    community_hits: list[dict[str, Any]]
    extraction_plan: list[dict[str, Any]]
    direct_evidence: list[dict[str, Any]]
    fallback_attempted: bool
    fallback_reason: str
    graph_trace: list[dict[str, Any]]
    run: QueryRun


def _append_trace(state: QueryGraphState, step: str, **payload: Any) -> list[dict[str, Any]]:
    trace = list(state.get("graph_trace") or [])
    trace.append({"step": step, **payload})
    return trace


def load_context_node(state: QueryGraphState) -> QueryGraphState:
    wiki_root = state["wiki_root"]
    modules = load_modules(wiki_root)
    symbols = load_symbols(wiki_root)
    communities = load_communities(wiki_root)
    return {
        "modules": modules,
        "symbols": symbols,
        "communities": communities,
        "graph_trace": _append_trace(
            state,
            "load_context",
            module_count=len(modules),
            symbol_count=len(symbols),
            community_count=len(communities),
        ),
    }


def semantic_intake_node(state: QueryGraphState) -> QueryGraphState:
    intake = semantic_intake(state["question"])
    return {
        "semantic_intake": intake,
        "graph_trace": _append_trace(
            state,
            "semantic_intake",
            question_type=intake.get("question_type"),
            confidence=intake.get("confidence"),
            cross_repo_likely=intake.get("cross_repo_likely"),
        ),
    }


def route_node(state: QueryGraphState) -> QueryGraphState:
    selected, rejected, tokens = route_modules(
        state["question"],
        state["modules"],
        top=int(state.get("top") or 5),
    )
    semantic_route = semantic_route_explanation(
        state.get("semantic_intake") or {},
        selected,
        rejected[:10],
    )
    return {
        "selected_modules": selected,
        "rejected_modules": rejected[:10],
        "tokens": tokens,
        "semantic_route": semantic_route,
        "graph_trace": _append_trace(
            state,
            "route",
            selected_count=len(selected),
            rejected_count=len(rejected),
            tokens=tokens,
            ambiguity=semantic_route.get("ambiguity"),
            needs_fixed_matrix=semantic_route.get("needs_fixed_matrix"),
        ),
    }


def symbol_hints_node(state: QueryGraphState) -> QueryGraphState:
    hints = find_symbol_hints(
        state["question"],
        state["symbols"],
        state.get("selected_modules") or [],
    )
    return {
        "symbol_hints": hints,
        "graph_trace": _append_trace(state, "symbol_hints", symbol_hint_count=len(hints)),
    }


def navigate_node(state: QueryGraphState) -> QueryGraphState:
    hits = find_community_hits(
        state["question"],
        state["communities"],
        state.get("selected_modules") or [],
    )
    return {
        "community_hits": hits,
        "graph_trace": _append_trace(state, "navigate", community_hit_count=len(hits)),
    }


def plan_node(state: QueryGraphState) -> QueryGraphState:
    plan = plan_extraction(
        state.get("community_hits") or [],
        state.get("symbol_hints") or [],
        question=state["question"],
    )
    for item in plan:
        item["question"] = state["question"]
    sufficiency = evidence_sufficiency(
        state["question"],
        state.get("semantic_intake") or {},
        state.get("selected_modules") or [],
        state.get("symbol_hints") or [],
        state.get("community_hits") or [],
        plan,
        state.get("direct_evidence") or [],
        bool(state.get("fallback_attempted")),
    )
    return {
        "extraction_plan": plan,
        "evidence_sufficiency": sufficiency,
        "graph_trace": _append_trace(
            state,
            "plan",
            extraction_plan_count=len(plan),
            evidence_sufficiency_status=sufficiency.get("status"),
            evidence_next_step=sufficiency.get("next_step"),
        ),
    }


def should_extract(state: QueryGraphState) -> str:
    if state.get("extract") and state.get("extraction_plan"):
        return "extract"
    return "finalize"


def extract_node(state: QueryGraphState) -> QueryGraphState:
    direct_evidence = run_extraction(
        state["wiki_root"],
        state.get("extraction_plan") or [],
        int(state.get("extract_limit") or 3),
    )
    sufficiency = evidence_sufficiency(
        state["question"],
        state.get("semantic_intake") or {},
        state.get("selected_modules") or [],
        state.get("symbol_hints") or [],
        state.get("community_hits") or [],
        state.get("extraction_plan") or [],
        direct_evidence,
        bool(state.get("fallback_attempted")),
    )
    return {
        "direct_evidence": direct_evidence,
        "evidence_sufficiency": sufficiency,
        "graph_trace": _append_trace(
            state,
            "extract",
            direct_evidence_count=len(direct_evidence),
            evidence_sufficiency_status=sufficiency.get("status"),
            evidence_next_step=sufficiency.get("next_step"),
        ),
    }


def _useful_direct_evidence_count(state: QueryGraphState) -> int:
    useful_kinds = {"method", "method-chunk", "class", "enum", "property", "line-window", "file"}
    return sum(1 for item in state.get("direct_evidence") or [] if item.get("kind") in useful_kinds)


def should_fallback_after_extract(state: QueryGraphState) -> str:
    if state.get("fallback_attempted"):
        return "finalize"
    plan = state.get("extraction_plan") or []
    if not state.get("extract") or not plan:
        return "finalize"

    extract_limit = int(state.get("extract_limit") or 3)
    useful_count = _useful_direct_evidence_count(state)
    has_symbol_only = bool(state.get("direct_evidence")) and useful_count == 0
    too_narrow = extract_limit < min(4, len(plan))
    if has_symbol_only or (too_narrow and useful_count > 0):
        return "fallback_expand_extract"
    return "finalize"


def fallback_expand_extract_node(state: QueryGraphState) -> QueryGraphState:
    plan = state.get("extraction_plan") or []
    old_limit = int(state.get("extract_limit") or 3)
    new_limit = min(max(old_limit + 3, 4), 4, len(plan))
    reason = (
        "expanded extraction because first graph pass was too narrow"
        if old_limit < new_limit
        else "fallback checked but extraction limit could not expand"
    )
    return {
        "extract_limit": new_limit,
        "fallback_attempted": True,
        "fallback_reason": reason,
        "graph_trace": _append_trace(
            state,
            "fallback_expand_extract",
            reason=reason,
            old_extract_limit=old_limit,
            new_extract_limit=new_limit,
            useful_direct_evidence_count=_useful_direct_evidence_count(state),
        ),
    }


def finalize_node(state: QueryGraphState) -> QueryGraphState:
    run = QueryRun(question=state["question"], wiki_root=state["wiki_root"])
    run.selected_modules = state.get("selected_modules") or []
    run.rejected_modules = state.get("rejected_modules") or []
    run.symbol_hints = state.get("symbol_hints") or []
    run.community_hits = state.get("community_hits") or []
    run.extraction_plan = state.get("extraction_plan") or []
    run.direct_evidence = state.get("direct_evidence") or []
    run.semantic_intake = state.get("semantic_intake") or {}
    run.semantic_route = state.get("semantic_route") or {}
    run.evidence_sufficiency = state.get("evidence_sufficiency") or evidence_sufficiency(
        state["question"],
        run.semantic_intake,
        run.selected_modules,
        run.symbol_hints,
        run.community_hits,
        run.extraction_plan,
        run.direct_evidence,
        bool(state.get("fallback_attempted")),
    )
    run.inference = [
        {
            "kind": "module-routing",
            "note": "Selected modules are routing candidates from wiki metadata, not proof of detailed source logic.",
            "selected_module_ids": [hit.module_id for hit in run.selected_modules],
        },
        {
            "kind": "community-navigation",
            "note": "Community hits are deterministic navigation candidates from Graphify metadata, not proof of detailed source logic.",
            "community_hit_ids": [hit.get("id") for hit in run.community_hits],
        },
        {
            "kind": "langgraph-orchestration",
            "note": "This run was orchestrated by LangGraph nodes over deterministic routing, navigation, planning, extraction, and challenge steps.",
        },
        {
            "kind": "semantic-intake",
            "note": "Semantic intake is an agent-readable hypothesis about the user question; source code evidence still wins.",
            "question_type": run.semantic_intake.get("question_type"),
            "confidence": run.semantic_intake.get("confidence"),
        },
        {
            "kind": "evidence-sufficiency",
            "note": "Evidence sufficiency tells the answering agent whether it can answer, should extract/read more files, or should harden the wiki.",
            "status": run.evidence_sufficiency.get("status"),
            "next_step": run.evidence_sufficiency.get("next_step"),
            "can_answer": run.evidence_sufficiency.get("can_answer"),
        },
    ]
    run.open_questions = [
        "細節邏輯需以 DynamicCodeProvider evidence 為準；routing/community 只作導航。"
    ]
    if run.evidence_sufficiency.get("needs_more_evidence"):
        run.open_questions.append(
            f"Evidence sufficiency is {run.evidence_sufficiency.get('status')}; next step: {run.evidence_sufficiency.get('next_step')}."
        )
    run.trace.extend(state.get("graph_trace") or [])
    if state.get("fallback_attempted"):
        run.inference.append(
            {
                "kind": "langgraph-fallback",
                "note": state.get("fallback_reason") or "Graph fallback was attempted.",
                "extract_limit": state.get("extract_limit"),
            }
        )
    run.trace.append(
        {
            "step": "finalize",
            "selected_count": len(run.selected_modules),
            "community_hit_count": len(run.community_hits),
            "extraction_plan_count": len(run.extraction_plan),
            "direct_evidence_count": len(run.direct_evidence),
            "semantic_question_type": run.semantic_intake.get("question_type"),
            "evidence_sufficiency_status": run.evidence_sufficiency.get("status"),
        }
    )
    challenge_query_run(run)
    run.trace.append(
        {
            "step": "challenge",
            "challenge_passed": run.passed_challenge(),
            "finding_count": len(run.challenge_findings),
        }
    )
    return {
        "run": run,
        "graph_trace": _append_trace(
            state,
            "challenge",
            challenge_passed=run.passed_challenge(),
            finding_count=len(run.challenge_findings),
        ),
    }


def compile_query_graph():
    graph = StateGraph(QueryGraphState)
    graph.add_node("load_context", load_context_node)
    graph.add_node("semantic_intake", semantic_intake_node)
    graph.add_node("route", route_node)
    graph.add_node("symbol_hints", symbol_hints_node)
    graph.add_node("navigate", navigate_node)
    graph.add_node("plan", plan_node)
    graph.add_node("extract", extract_node)
    graph.add_node("fallback_expand_extract", fallback_expand_extract_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "semantic_intake")
    graph.add_edge("semantic_intake", "route")
    graph.add_edge("route", "symbol_hints")
    graph.add_edge("symbol_hints", "navigate")
    graph.add_edge("navigate", "plan")
    graph.add_conditional_edges(
        "plan",
        should_extract,
        {
            "extract": "extract",
            "finalize": "finalize",
        },
    )
    graph.add_conditional_edges(
        "extract",
        should_fallback_after_extract,
        {
            "fallback_expand_extract": "fallback_expand_extract",
            "finalize": "finalize",
        },
    )
    graph.add_edge("fallback_expand_extract", "extract")
    graph.add_edge("finalize", END)
    return graph.compile()


def build_query_run_graph(
    wiki_root: Path,
    question: str,
    top: int,
    extract: bool = False,
    extract_limit: int = 3,
) -> QueryRun:
    app = compile_query_graph()
    final_state = app.invoke(
        {
            "wiki_root": wiki_root.resolve(),
            "question": question,
            "top": top,
            "extract": extract,
            "extract_limit": extract_limit,
            "fallback_attempted": False,
            "graph_trace": [],
        }
    )
    return final_state["run"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM Wiki LangGraph query runtime")
    parser.add_argument("--wiki-root", default=".", help="Path to llm-wiki root")
    parser.add_argument("--question", required=True, help="Question or requirement to route")
    parser.add_argument("--top", type=int, default=5, help="Max module candidates")
    parser.add_argument("--extract", action="store_true", help="Run DynamicCodeProvider for planned files")
    parser.add_argument("--extract-limit", type=int, default=3, help="Max planned files to extract")
    args = parser.parse_args(argv)

    wiki_root = Path(args.wiki_root).resolve()
    run = build_query_run_graph(
        wiki_root,
        args.question,
        args.top,
        extract=args.extract,
        extract_limit=args.extract_limit,
    )
    out_path = save_query_run(run)
    print_summary(run, out_path)
    return 0 if run.passed_challenge() else 2


if __name__ == "__main__":
    raise SystemExit(main())
