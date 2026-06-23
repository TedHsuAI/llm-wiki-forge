from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from .challenge import challenge_query_run
from .code_provider import DynamicCodeProvider
from .community_nav import find_community_hits
from .io import load_communities, load_modules, load_symbols, slugify, write_json
from .models import ModuleHit, QueryRun
from .planner import plan_extraction
from .router import route_modules, tokenize
from .semantic import evidence_sufficiency, semantic_intake, semantic_route_explanation


def symbol_matches_selected_module(symbol: dict[str, Any], selected_modules: list[ModuleHit]) -> tuple[bool, str]:
    symbol_module = str(symbol.get("module") or symbol.get("module_id") or "").lower()
    symbol_solution = str(symbol.get("solution_group") or "").lower()
    source_paths = [str(path).lower() for path in symbol.get("source_paths") or []]

    for module in selected_modules:
        if symbol_module and symbol_module == module.name.lower():
            return True, module.module_id
        if symbol_solution and symbol_solution == module.solution_group.lower() and symbol_module and module.module_id.lower().endswith(symbol_module.replace(".", "-").replace("_", "-")):
            return True, module.module_id
        for module_path in module.source_paths:
            module_path_lower = module_path.lower()
            if any(path.startswith(module_path_lower) for path in source_paths):
                return True, module.module_id
    return False, ""


def find_symbol_hints(question: str, symbols: list[dict[str, Any]], selected_modules: list[ModuleHit], limit: int = 10) -> list[dict[str, Any]]:
    tokens = set(tokenize(question))
    hints: list[dict[str, Any]] = []
    for symbol in symbols:
        in_scope, module_id = symbol_matches_selected_module(symbol, selected_modules)
        if not in_scope:
            continue
        haystack = " ".join(
            str(symbol.get(key) or "")
            for key in ("id", "name", "kind", "business_context", "skill_description", "technical_contract", "impact_analysis")
        ).lower()
        score = sum(1 for token in tokens if token and token in haystack)
        if score <= 0:
            continue
        hints.append(
            {
                "id": symbol.get("id"),
                "name": symbol.get("name"),
                "kind": symbol.get("kind"),
                "solution_group": symbol.get("solution_group"),
                "module": symbol.get("module"),
                "project": symbol.get("project"),
                "module_id": module_id,
                "score": score,
                "source_paths": symbol.get("source_paths") or [],
                "technical_contract": symbol.get("technical_contract") or {},
            }
        )
    hints.sort(key=lambda item: item["score"], reverse=True)
    return hints[:limit]


def run_extraction(wiki_root: Path, extraction_plan: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    provider = DynamicCodeProvider(wiki_root)
    direct_evidence: list[dict[str, Any]] = []
    for item in extraction_plan[:limit]:
        result = provider.get_context(
            repo_id=str(item.get("repo_id") or item.get("module_id") or ""),
            file_paths=[str(item["file_path"])],
            focus_symbols=[str(symbol) for symbol in item.get("focus_symbols") or [] if symbol],
            max_chars=12000,
            max_symbols_per_file=2,
            query=str(item.get("question") or ""),
        )
        for evidence in result.get("code_evidence") or []:
            evidence["planning_reason"] = item.get("reason")
            evidence["planning_source"] = item.get("source")
            evidence["planning_intent_score"] = item.get("intent_score")
            evidence["planning_intent_trace"] = item.get("intent_trace")
            evidence["module_id"] = item.get("module_id")
            evidence["community_id"] = item.get("community_id")
            direct_evidence.append(evidence)
        for error in result.get("errors") or []:
            direct_evidence.append(
                {
                    "kind": "extraction-error",
                    "module_id": item.get("module_id"),
                    "file_path": error.get("file_path"),
                    "error": error.get("error"),
                    "confidence": 0.0,
                }
            )
    return direct_evidence


def build_query_run(wiki_root: Path, question: str, top: int, extract: bool = False, extract_limit: int = 3) -> QueryRun:
    modules = load_modules(wiki_root)
    symbols = load_symbols(wiki_root)
    communities = load_communities(wiki_root)
    selected, rejected, tokens = route_modules(question, modules, top=top)

    run = QueryRun(question=question, wiki_root=wiki_root)
    run.semantic_intake = semantic_intake(question)
    run.selected_modules = selected
    run.rejected_modules = rejected[:10]
    run.semantic_route = semantic_route_explanation(run.semantic_intake, selected, run.rejected_modules)
    run.symbol_hints = find_symbol_hints(
        question,
        symbols,
        selected,
    )
    run.community_hits = find_community_hits(question, communities, selected)
    run.extraction_plan = plan_extraction(run.community_hits, run.symbol_hints, question=question)
    for item in run.extraction_plan:
        item["question"] = question
    if extract and run.extraction_plan:
        run.direct_evidence = run_extraction(wiki_root, run.extraction_plan, extract_limit)
    run.evidence_sufficiency = evidence_sufficiency(
        question,
        run.semantic_intake,
        run.selected_modules,
        run.symbol_hints,
        run.community_hits,
        run.extraction_plan,
        run.direct_evidence,
    )
    run.inference = [
        {
            "kind": "module-routing",
            "note": "Selected modules are routing candidates from wiki metadata, not proof of detailed source logic.",
            "selected_module_ids": [hit.module_id for hit in selected],
        },
        {
            "kind": "community-navigation",
            "note": "Community hits are deterministic navigation candidates from Graphify metadata, not proof of detailed source logic.",
            "community_hit_ids": [hit.get("id") for hit in run.community_hits],
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
        }
    ]
    run.open_questions = [
        "P0 尚未讀取 source code；細節邏輯需交給 DynamicCodeProvider 或 focused repomix 驗證。"
    ]
    if run.evidence_sufficiency.get("needs_more_evidence"):
        run.open_questions.append(
            f"Evidence sufficiency is {run.evidence_sufficiency.get('status')}; next step: {run.evidence_sufficiency.get('next_step')}."
        )
    run.trace.append(
        {
            "step": "route_modules",
            "tokens": tokens,
            "module_count": len(modules),
            "symbol_count": len(symbols),
            "community_count": len(communities),
            "selected_count": len(selected),
            "semantic_question_type": run.semantic_intake.get("question_type"),
            "semantic_route_ambiguity": run.semantic_route.get("ambiguity"),
            "community_hit_count": len(run.community_hits),
            "extraction_plan_count": len(run.extraction_plan),
            "direct_evidence_count": len(run.direct_evidence),
            "evidence_sufficiency_status": run.evidence_sufficiency.get("status"),
        }
    )
    challenge_query_run(run)
    return run


def save_query_run(run: QueryRun) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = run.wiki_root / "Wiki" / "_data" / "query_runs"
    out_path = out_dir / f"{stamp}_{slugify(run.question)}.json"
    write_json(out_path, run.to_dict())
    return out_path


def print_summary(run: QueryRun, out_path: Path) -> None:
    status = "PASS" if run.passed_challenge() else "FAIL"
    print(f"challenge: {status}")
    print(f"evidence_pack: {out_path}")
    semantic = run.semantic_intake or {}
    sufficiency = run.evidence_sufficiency or {}
    if semantic:
        print(
            "semantic: "
            f"type={semantic.get('question_type')} "
            f"confidence={semantic.get('confidence')} "
            f"route_ambiguity={(run.semantic_route or {}).get('ambiguity')}"
        )
    if sufficiency:
        print(
            "evidence_sufficiency: "
            f"status={sufficiency.get('status')} "
            f"can_answer={sufficiency.get('can_answer')} "
            f"next_step={sufficiency.get('next_step')}"
        )
    print("selected_modules:")
    for hit in run.selected_modules:
        print(f"- {hit.module_id} | {hit.name} | score={hit.score:.2f}")
        for reason in hit.reasons[:3]:
            print(f"  - {reason}")
    if run.challenge_findings:
        print("challenge_findings:")
        for finding in run.challenge_findings:
            print(f"- [{finding.severity}] {finding.code}: {finding.message}")
    if run.community_hits:
        print("community_hits:")
        for hit in run.community_hits[:5]:
            print(f"- {hit['id']} | score={hit['score']:.2f} | {hit['title']}")
    if run.extraction_plan:
        print("extraction_plan:")
        for item in run.extraction_plan[:5]:
            print(
                f"- {item['file_path']} | source={item['source']} "
                f"| intent_score={item.get('intent_score')} | reason={item['reason']}"
            )
    if run.direct_evidence:
        print("direct_evidence:")
        for item in run.direct_evidence[:5]:
            if item.get("kind") == "extraction-error":
                print(f"- ERROR {item.get('file_path')}: {item.get('error')}")
            else:
                print(
                    f"- {item.get('symbol') or item.get('kind')} "
                    f"{item.get('file_path')}:{item.get('start_line')}-{item.get('end_line')} "
                    f"method={item.get('extraction_method')} confidence={item.get('confidence')}"
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM Wiki P0 query runtime")
    parser.add_argument("--wiki-root", default=".", help="Path to llm-wiki root")
    parser.add_argument("--question", required=True, help="Question or requirement to route")
    parser.add_argument("--top", type=int, default=5, help="Max module candidates")
    parser.add_argument("--extract", action="store_true", help="Run DynamicCodeProvider for the first planned files")
    parser.add_argument("--extract-limit", type=int, default=3, help="Max planned files to extract")
    args = parser.parse_args(argv)

    wiki_root = Path(args.wiki_root).resolve()
    run = build_query_run(wiki_root, args.question, args.top, extract=args.extract, extract_limit=args.extract_limit)
    out_path = save_query_run(run)
    print_summary(run, out_path)
    return 0 if run.passed_challenge() else 2


if __name__ == "__main__":
    raise SystemExit(main())
