from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from .io import load_json, write_json
from .graph_runtime import build_query_run_graph
from .query import build_query_run


def evaluate_case(wiki_root: Path, case: dict[str, Any], runtime: str = "classic") -> dict[str, Any]:
    runtimes = case.get("runtimes")
    if runtimes and runtime not in runtimes:
        return {
            "id": case["id"],
            "question": case["question"],
            "runtime": runtime,
            "passed": True,
            "skipped": True,
            "findings": [],
        }
    builder = build_query_run_graph if runtime == "graph" else build_query_run
    run = builder(
        wiki_root,
        str(case["question"]),
        top=5,
        extract=bool(
            case.get("require_method_evidence")
            or case.get("require_method_or_enum_evidence")
            or case.get("require_chunk_evidence")
            or case.get("expected_direct_file_contains_any")
            or case.get("expected_direct_file_contains_all")
        ),
        extract_limit=int(case.get("extract_limit") or 3),
    )
    selected_ids = [module.module_id for module in run.selected_modules]
    community_module_ids = [str(hit.get("module_id")) for hit in run.community_hits]
    expected_modules = case.get("expected_primary_modules") or []
    expected_communities = case.get("expected_any_communities") or []

    findings: list[str] = []
    if case.get("expect_no_module"):
        if selected_ids:
            findings.append(f"Expected no modules, got {selected_ids[:5]}")
    else:
        missing = [module_id for module_id in expected_modules if module_id not in selected_ids]
        if missing:
            findings.append(f"Missing expected modules: {missing}")
        missing_communities = [
            module_id
            for module_id in expected_communities
            if module_id not in community_module_ids
        ]
        if missing_communities:
            findings.append(f"Missing expected community module hits: {missing_communities}")
        if case.get("require_method_evidence"):
            method_count = sum(1 for item in run.direct_evidence if item.get("kind") == "method")
            class_count = sum(1 for item in run.direct_evidence if item.get("kind") == "class")
            if method_count == 0:
                findings.append("Expected method-level evidence, got none.")
            if class_count > method_count and class_count > 0 and not case.get("allow_class_context"):
                findings.append(f"Class-level evidence dominates method-level evidence: class={class_count}, method={method_count}")
        if case.get("require_method_or_enum_evidence"):
            useful_count = sum(1 for item in run.direct_evidence if item.get("kind") in {"method", "enum", "property"})
            if useful_count == 0:
                findings.append("Expected method/enum/property evidence, got none.")
        if case.get("require_chunk_evidence"):
            chunk_items = [item for item in run.direct_evidence if item.get("kind") == "method-chunk"]
            if not chunk_items:
                findings.append("Expected method-chunk evidence, got none.")
            expected_parents = case.get("expected_parent_symbols") or []
            parent_symbols = {item.get("parent_symbol") for item in chunk_items}
            missing_parents = [symbol for symbol in expected_parents if symbol not in parent_symbols]
            if missing_parents:
                findings.append(f"Missing expected chunk parent symbols: {missing_parents}")
            expected_first_hints = case.get("expected_first_chunk_hint_any") or []
            if chunk_items and expected_first_hints:
                first_hint = str(chunk_items[0].get("chunk_hint") or "")
                if not any(hint in first_hint.split(",") for hint in expected_first_hints):
                    findings.append(
                        "First chunk hint does not match query intent: "
                        f"expected any {expected_first_hints}, got {first_hint!r}"
                    )
            oversized_chunks = [
                item
                for item in chunk_items
                if int(item.get("end_line") or 0) - int(item.get("start_line") or 0) + 1 > 180
            ]
            if oversized_chunks:
                findings.append(f"Chunk evidence is still too large: {len(oversized_chunks)} oversized chunk(s).")
        direct_files = [str(item.get("file_path") or "").lower() for item in run.direct_evidence]
        expected_file_any = [str(fragment).lower() for fragment in case.get("expected_direct_file_contains_any") or []]
        expected_file_all = [str(fragment).lower() for fragment in case.get("expected_direct_file_contains_all") or []]
        if expected_file_any and not any(
            any(fragment in file_path for file_path in direct_files)
            for fragment in expected_file_any
        ):
            findings.append(f"Missing any expected direct evidence file fragments: {expected_file_any}")
        missing_file_fragments = [
            fragment
            for fragment in expected_file_all
            if not any(fragment in file_path for file_path in direct_files)
        ]
        if missing_file_fragments:
            findings.append(f"Missing expected direct evidence file fragments: {missing_file_fragments}")
        if case.get("require_intent_trace"):
            planned = run.extraction_plan
            if not planned:
                findings.append("Expected extraction plan with intent trace, got no plan.")
            else:
                first_trace = planned[0].get("intent_trace") or {}
                if not first_trace.get("matched_intent_terms") and not first_trace.get("matched_query_tokens"):
                    findings.append(f"First extraction plan has no observable intent matches: {first_trace}")
                if int(planned[0].get("intent_score") or 0) <= 0:
                    findings.append(f"First extraction plan has non-positive intent_score: {planned[0].get('intent_score')}")
        expected_methods = [str(method) for method in case.get("expected_extraction_methods_any") or []]
        if expected_methods:
            methods = [str(item.get("extraction_method") or "") for item in run.direct_evidence]
            if not any(method in methods for method in expected_methods):
                findings.append(f"Missing any expected extraction methods: {expected_methods}")
        forbidden_class_fragments = [str(fragment).lower() for fragment in case.get("forbid_class_evidence_file_contains") or []]
        if forbidden_class_fragments:
            offending = [
                item.get("file_path")
                for item in run.direct_evidence
                if item.get("kind") == "class"
                and any(fragment in str(item.get("file_path") or "").lower() for fragment in forbidden_class_fragments)
            ]
            if offending:
                findings.append(f"Forbidden class-level evidence remained: {offending}")
        expected_trace_steps = [str(step) for step in case.get("expected_trace_steps") or []]
        if expected_trace_steps:
            trace_steps = [str(item.get("step") or "") for item in run.trace]
            missing_steps = [step for step in expected_trace_steps if step not in trace_steps]
            if missing_steps:
                findings.append(f"Missing expected trace steps: {missing_steps}")

    hard_errors = [finding.to_dict() for finding in run.challenge_findings if finding.severity == "error"]
    if hard_errors and not case.get("expect_no_module"):
        findings.append(f"Unexpected challenge errors: {hard_errors}")
    if not hard_errors and case.get("expect_no_module"):
        findings.append("Expected challenge error for irrelevant query, but query passed.")

    return {
        "id": case["id"],
        "question": case["question"],
        "runtime": runtime,
        "passed": not findings,
        "findings": findings,
        "selected_modules": selected_ids,
        "community_hit_modules": community_module_ids,
        "challenge_passed": run.passed_challenge(),
        "challenge_findings": [finding.to_dict() for finding in run.challenge_findings],
        "trace_steps": [item.get("step") for item in run.trace],
        "direct_evidence_kinds": [item.get("kind") for item in run.direct_evidence],
        "direct_evidence_symbols": [item.get("symbol") for item in run.direct_evidence],
        "direct_evidence_files": [item.get("file_path") for item in run.direct_evidence],
        "direct_evidence_extraction_methods": [item.get("extraction_method") for item in run.direct_evidence],
        "extraction_plan_intent_scores": [item.get("intent_score") for item in run.extraction_plan],
        "extraction_plan_intent_traces": [item.get("intent_trace") for item in run.extraction_plan],
        "direct_evidence_parent_symbols": [item.get("parent_symbol") for item in run.direct_evidence if item.get("parent_symbol")],
        "direct_evidence_chunk_hints": [item.get("chunk_hint") for item in run.direct_evidence if item.get("kind") == "method-chunk"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate LLM Wiki query runtime against gold set")
    parser.add_argument("--wiki-root", default=".")
    parser.add_argument("--gold-set", default="Wiki/_eval/query_gold_set.json")
    parser.add_argument("--runtime", choices=["classic", "graph"], default="classic")
    args = parser.parse_args(argv)

    wiki_root = Path(args.wiki_root).resolve()
    gold_path = Path(args.gold_set)
    if not gold_path.is_absolute():
        gold_path = wiki_root / gold_path
    gold = load_json(gold_path)

    results = [evaluate_case(wiki_root, case, runtime=args.runtime) for case in gold.get("cases") or []]
    active_results = [result for result in results if not result.get("skipped")]
    passed = sum(1 for result in active_results if result["passed"])
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = wiki_root / "Wiki" / "_eval" / "eval_runs" / f"query_eval_{args.runtime}_{stamp}.json"
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "gold_set": str(gold_path),
        "runtime": args.runtime,
        "case_count": len(active_results),
        "skipped": len(results) - len(active_results),
        "passed": passed,
        "failed": len(active_results) - passed,
        "results": results,
    }
    write_json(out_path, payload)

    print(f"eval_run: {out_path}")
    print(f"passed: {passed}/{len(active_results)}")
    for result in results:
        if result.get("skipped"):
            print(f"- SKIP {result['id']}")
            continue
        status = "PASS" if result["passed"] else "FAIL"
        print(f"- {status} {result['id']}")
        for finding in result["findings"]:
            print(f"  - {finding}")
    return 0 if passed == len(active_results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
