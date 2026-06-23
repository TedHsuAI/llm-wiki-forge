from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .graph_runtime import build_query_run_graph
from .hybrid_ranker import build_shadow_hybrid_ranking
from .io import load_modules
from .models import ModuleHit, QueryRun
from .query import run_extraction, save_query_run
from .semantic import evidence_sufficiency, semantic_intake
from .source_search import DISPATCH_ROOT, search_source


FLOW = [
    "semantic_intake",
    "graph_runtime",
    "evidence_gate",
    "ambiguity_gate",
    "source_search",
    "read_verify",
    "answer_gate",
]

IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])-?\d+(?![A-Za-z0-9_])")
IDENTIFIER_STOPWORDS = {
    "api",
    "app",
    "core",
    "coreserver",
    "coreservers",
    "controller",
    "dispatch",
    "dispatchrule",
    "endpoint",
    "false",
    "get",
    "post",
    "rd",
    "request",
    "response",
    "server",
    "service",
    "sql",
    "status",
    "system",
    "tgds",
    "true",
    "webapi",
}
SCOPE_HINTS = [
    (
        ["coreservers", "core servers", "tdc"],
        "/home/tedhsu/DispatchRawdata/RD.TGDS/DEV/TGDS/CoreServers",
        "CoreServers",
    ),
    (
        ["tgds.webapi", "taxiplus", "taxiplus webapi"],
        "/home/tedhsu/DispatchRawdata/RD.TGDS/DEV/TGDS-TaxiPlus/01_Code/TGDS.WebAPI",
        "TGDS.WebAPI",
    ),
    (
        ["dispatch-webapi", "dispatch webapi", "tgds-dispatch-webapi"],
        "/home/tedhsu/DispatchRawdata/TGDS-Dispatch-WebAPI",
        "TGDS-Dispatch-WebAPI",
    ),
    (
        ["dispatchrule", "dispatch rule"],
        "/home/tedhsu/DispatchRawdata/DispatchRule",
        "DispatchRule",
    ),
]
QUOTE_RE = re.compile(r"[「『“\"']([^」』”\"']{2,})[」』”\"']")
QUESTION_SPLIT_RE = re.compile(
    r"[^\w\u4e00-\u9fff]+|"
    r"(?:我該|我要|請問|怎麼|如何|什麼|代表|幫我|應該|可以|"
    r"從|中|出|為|是|的|了|和|跟|與|在|到|用|把)"
)
NATURAL_STOPWORDS = {
    "問題",
    "資訊",
    "資料",
    "程式",
    "內容",
    "邏輯",
    "判斷",
    "狀態",
    "查詢",
    "搜尋",
    "過濾",
    "司機",
    "營業狀態",
    "從業狀態",
    "空車",
}
def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _looks_like_exact_identifier(term: str) -> bool:
    lowered = term.lower()
    if lowered in IDENTIFIER_STOPWORDS:
        return False
    if "_" in term:
        return True
    if any(ch.isdigit() for ch in term):
        return True
    if term.isupper() and len(term) >= 3:
        return True
    if re.search(r"[a-z][A-Z]|[A-Z][a-z]", term):
        return True
    return False


def exact_identifiers(question: str) -> list[str]:
    terms = [match.group(0) for match in IDENTIFIER_RE.finditer(question)]
    return _dedupe([term for term in terms if _looks_like_exact_identifier(term)])


def queried_values(question: str) -> list[str]:
    return _dedupe([match.group(0) for match in NUMBER_RE.finditer(question)])


def quoted_phrases(question: str) -> list[str]:
    return _dedupe([match.group(1).strip() for match in QUOTE_RE.finditer(question) if match.group(1).strip()])


def natural_question_terms(question: str, identifiers: list[str], values: list[str]) -> list[str]:
    terms: list[str] = []
    terms.extend(quoted_phrases(question))
    for piece in QUESTION_SPLIT_RE.split(question):
        term = piece.strip()
        if len(term) < 2:
            continue
        if term.lower() in IDENTIFIER_STOPWORDS:
            continue
        if term in NATURAL_STOPWORDS:
            continue
        terms.append(term)
    terms.extend(identifiers)
    terms.extend(values)
    return _dedupe(terms)


def high_signal_terms(question_terms: list[str], identifiers: list[str], values: list[str], quoted: list[str]) -> list[str]:
    high_signal: list[str] = []
    for term in question_terms:
        if term in quoted or term in identifiers or term in values:
            high_signal.append(term)
            continue
        if _looks_like_exact_identifier(term):
            high_signal.append(term)
            continue
        if term.isascii() and len(term) >= 4 and term.lower() not in IDENTIFIER_STOPWORDS:
            high_signal.append(term)
            continue
        if len(term) >= 4 and term not in NATURAL_STOPWORDS and not term.isascii():
            high_signal.append(term)
    return _dedupe(high_signal)


def explicit_scope_roots(question: str) -> tuple[list[str], list[str]]:
    lowered = question.lower()
    roots: list[str] = []
    labels: list[str] = []
    for hints, root, label in SCOPE_HINTS:
        if any(hint in lowered for hint in hints):
            roots.append(root)
            labels.append(label)
    return _dedupe(roots), _dedupe(labels)


def _direct_evidence_text(run: QueryRun | None) -> str:
    if run is None:
        return ""
    chunks: list[str] = []
    for item in run.direct_evidence:
        chunks.append(str(item.get("file_path") or ""))
        chunks.append(str(item.get("symbol") or ""))
        chunks.append(str(item.get("code") or ""))
    return "\n".join(chunks).lower()


def _direct_evidence_items(run: QueryRun | None) -> list[dict[str, str]]:
    if run is None:
        return []
    items: list[dict[str, str]] = []
    for item in run.direct_evidence:
        text = "\n".join(
            str(item.get(key) or "")
            for key in ("file_path", "symbol", "code")
        )
        items.append(
            {
                "file_path": str(item.get("file_path") or ""),
                "symbol": str(item.get("symbol") or ""),
                "text": text.lower(),
            }
        )
    return items


def _useful_direct_count(run: QueryRun | None) -> int:
    if run is None:
        return 0
    useful = {"method", "method-chunk", "class", "enum", "property", "line-window", "file"}
    return sum(1 for item in run.direct_evidence if item.get("kind") in useful)


def selected_module_summaries(run: QueryRun | None) -> list[dict[str, Any]]:
    if run is None:
        return []
    return [
        {
            "module_id": hit.module_id,
            "name": hit.name,
            "score": round(hit.score, 4),
            "solution_group": hit.solution_group,
            "source_paths": hit.source_paths[:5],
            "reasons": hit.reasons[:3],
        }
        for hit in run.selected_modules[:5]
    ]


def build_coverage(run: QueryRun | None, question: str, identifiers: list[str], values: list[str]) -> dict[str, Any]:
    quoted = quoted_phrases(question)
    terms = natural_question_terms(question, identifiers, values)
    high_signal = high_signal_terms(terms, identifiers, values, quoted)
    direct_text = _direct_evidence_text(run)
    covered = [term for term in terms if term.lower() in direct_text]
    missing = [term for term in terms if term.lower() not in direct_text]
    covered_high_signal = [term for term in high_signal if term.lower() in direct_text]
    missing_high_signal = [term for term in high_signal if term.lower() not in direct_text]
    direct_items: list[dict[str, Any]] = []
    if run is not None:
        for item in run.direct_evidence[:8]:
            item_text = "\n".join(
                str(item.get(key) or "")
                for key in ("file_path", "symbol", "code")
            ).lower()
            matched_terms = [term for term in terms if term.lower() in item_text]
            direct_items.append(
                {
                    "file_path": item.get("file_path"),
                    "symbol": item.get("symbol"),
                    "kind": item.get("kind"),
                    "start_line": item.get("start_line"),
                    "end_line": item.get("end_line"),
                    "matched_question_terms": matched_terms,
                }
            )
    return {
        "question_terms": terms,
        "quoted_phrases": quoted,
        "high_signal_terms": high_signal,
        "covered_terms": covered,
        "missing_terms": missing,
        "covered_high_signal_terms": covered_high_signal,
        "missing_high_signal_terms": missing_high_signal,
        "coverage_ratio": round(len(covered) / len(terms), 4) if terms else 1.0,
        "direct_evidence_terms_checked": bool(run and run.direct_evidence),
        "direct_evidence_items": direct_items,
        "coverage_basis": "direct evidence file_path, symbol, and code only",
    }


def candidate_sources(run: QueryRun | None, coverage: dict[str, Any]) -> dict[str, Any]:
    if run is None:
        return {"direct_evidence": [], "extraction_plan": [], "selected_modules": []}
    terms = [str(term) for term in coverage.get("question_terms") or []]
    direct_evidence: list[dict[str, Any]] = []
    for item in run.direct_evidence[:8]:
        item_text = "\n".join(
            str(item.get(key) or "")
            for key in ("file_path", "symbol", "code")
        ).lower()
        direct_evidence.append(
            {
                "file_path": item.get("file_path"),
                "symbol": item.get("symbol"),
                "kind": item.get("kind"),
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
                "extraction_method": item.get("extraction_method"),
                "matched_question_terms": [term for term in terms if term.lower() in item_text],
            }
        )
    extraction_plan = [
        {
            "file_path": item.get("file_path") or item.get("path"),
            "symbol": item.get("symbol"),
            "focus_symbols": item.get("focus_symbols"),
            "source": item.get("source"),
            "intent_score": item.get("intent_score"),
            "reason": item.get("reason"),
        }
        for item in run.extraction_plan[:8]
    ]
    return {
        "direct_evidence": direct_evidence,
        "extraction_plan": extraction_plan,
        "selected_modules": selected_module_summaries(run),
    }


def run_evidence_gate(run: QueryRun | None, identifiers: list[str], values: list[str]) -> dict[str, Any]:
    direct_text = _direct_evidence_text(run)
    direct_items = _direct_evidence_items(run)
    identifier_hits = [term for term in identifiers if term.lower() in direct_text]
    value_hits = [value for value in values if re.search(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])", direct_text)]
    supporting_items: list[dict[str, Any]] = []
    for item in direct_items:
        item_identifier_hits = [term for term in identifiers if term.lower() in item["text"]]
        item_value_hits = [
            value
            for value in values
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])", item["text"])
        ]
        if item_identifier_hits and len(item_value_hits) == len(values):
            supporting_items.append(
                {
                    "file_path": item["file_path"],
                    "symbol": item["symbol"],
                    "identifier_hits": item_identifier_hits,
                    "value_hits": item_value_hits,
                }
            )
    useful_count = _useful_direct_count(run)
    sufficiency = (run.evidence_sufficiency if run else {}) or {}
    direct_evidence_count = len(run.direct_evidence if run else [])

    if identifiers:
        values_satisfied = not values or bool(supporting_items)
        passed = bool(identifier_hits) and values_satisfied and useful_count > 0
        status = "passed" if passed else "needs_source_search"
        if passed:
            reason = "exact identifier and requested values appear in direct evidence"
        elif not identifier_hits:
            reason = "exact identifier is absent from direct evidence, so graph evidence cannot be used as fact"
        elif values and not values_satisfied:
            reason = "exact identifier appears, but the requested numeric values are absent from direct evidence"
        else:
            reason = "direct evidence is not useful enough to answer"
    else:
        passed = bool(sufficiency.get("can_answer")) and useful_count > 0
        status = "passed" if passed else "needs_more_evidence"
        reason = (
            "semantic evidence sufficiency says direct evidence can answer"
            if passed
            else "direct evidence is weak, partial, empty, or not granular enough"
        )

    return {
        "step": "evidence_gate",
        "status": status,
        "can_answer_from_graph": passed,
        "exact_identifiers": identifiers,
        "queried_values": values,
        "identifier_hits_in_direct_evidence": identifier_hits,
        "value_hits_in_direct_evidence": value_hits,
        "supporting_direct_evidence_items": supporting_items[:5],
        "direct_evidence_count": direct_evidence_count,
        "useful_direct_evidence_count": useful_count,
        "semantic_status": sufficiency.get("status"),
        "semantic_next_step": sufficiency.get("next_step"),
        "reason": reason,
    }


def run_ambiguity_gate(
    question: str,
    intake: dict[str, Any],
    run: QueryRun | None,
    evidence_gate: dict[str, Any],
    coverage: dict[str, Any],
    scope_labels: list[str],
) -> dict[str, Any]:
    question_type = str(intake.get("question_type") or "unknown")
    route = (run.semantic_route if run else {}) or {}
    ambiguity = str(route.get("ambiguity") or "unknown")
    selected = selected_module_summaries(run)
    has_scope = bool(scope_labels)
    graph_can_answer = bool(evidence_gate.get("can_answer_from_graph"))
    direct_count = int(evidence_gate.get("useful_direct_evidence_count") or 0)
    has_high_signal = bool(coverage.get("high_signal_terms"))

    status_like = question_type == "status_logic" or any(term in question for term in ("營業狀態", "空車"))
    if status_like and not has_scope and not graph_can_answer and not has_high_signal:
        return {
            "step": "ambiguity_gate",
            "needs_user_clarification": True,
            "reason": "status wording can map to multiple source domains and no fact-grade direct evidence is available",
            "message": (
                "我目前找到多個可能方向，但還不能確定你要哪一種：\n"
                "1. IVE 車機狀態\n"
                "2. 司機/車輛營業狀態\n"
                "3. 派遣任務狀態\n"
                "你要我往哪一個查？"
            ),
            "options": ["IVE 車機狀態", "司機/車輛營業狀態", "派遣任務狀態"],
            "routing_candidates": selected,
            "route_ambiguity": ambiguity,
        }

    if (
        not has_scope
        and not graph_can_answer
        and direct_count == 0
        and ambiguity in {"medium", "high"}
        and len(selected) > 1
        and not evidence_gate.get("exact_identifiers")
        and not has_high_signal
    ):
        options = [item["name"] for item in selected[:3]]
        return {
            "step": "ambiguity_gate",
            "needs_user_clarification": True,
            "reason": "multiple routing candidates exist, but none is direct source evidence",
            "message": "我目前找到多個可能方向，但還不能把其中任何一個當作事實證據。你要我往哪個模組或檔案範圍查？",
            "options": options,
            "routing_candidates": selected,
            "route_ambiguity": ambiguity,
        }

    return {
        "step": "ambiguity_gate",
        "needs_user_clarification": False,
        "reason": "scope is explicit, graph evidence is sufficient, or deterministic source search can continue",
        "scope_hints": scope_labels,
        "routing_candidates": selected,
        "route_ambiguity": ambiguity,
    }


def source_patterns(question: str, intake: dict[str, Any], identifiers: list[str]) -> list[str]:
    if identifiers:
        return identifiers[:8]
    return []


def shadow_keyword_patterns(
    question: str,
    intake: dict[str, Any],
    identifiers: list[str],
    values: list[str],
    *,
    limit: int = 6,
) -> list[str]:
    quoted = quoted_phrases(question)
    terms = natural_question_terms(question, identifiers, values)
    high_signal = high_signal_terms(terms, identifiers, values, quoted)
    business_terms = [
        str(term).strip()
        for term in intake.get("business_terms") or []
        if str(term).strip()
    ]
    candidates = quoted + identifiers + high_signal + business_terms + values
    filtered: list[str] = []
    for term in candidates:
        lowered = term.lower()
        if lowered in IDENTIFIER_STOPWORDS or term in NATURAL_STOPWORDS:
            continue
        if term.isascii() and len(term) < 3:
            continue
        if not term.isascii() and len(term) < 2:
            continue
        filtered.append(term)
    return _dedupe(filtered)[: max(1, limit)]


def _env_flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 200) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def run_shadow_keyword_probe(
    *,
    wiki_root: Path,
    question: str,
    patterns: list[str],
    roots: list[str] | None,
    total_limit: int,
    per_pattern_limit: int,
) -> dict[str, Any] | None:
    if not patterns:
        return None
    matches: list[dict[str, Any]] = []
    errors: list[str] = []
    roots_seen: list[str] = []
    truncated = False
    searched_at: str | None = None
    for pattern in patterns:
        if len(matches) >= total_limit:
            truncated = True
            break
        remaining = total_limit - len(matches)
        result = search_source(
            wiki_root=wiki_root,
            query=question,
            patterns=[pattern],
            roots=roots,
            limit=min(per_pattern_limit, remaining),
            regex=False,
            timeout_seconds=12.0,
        )
        matches.extend(result.get("matches") or [])
        errors.extend(result.get("errors") or [])
        roots_seen.extend(str(root) for root in result.get("roots") or [])
        truncated = truncated or bool(result.get("truncated"))
        searched_at = str(result.get("searched_at") or searched_at or "")
    return {
        "query": question,
        "patterns": patterns,
        "roots": _dedupe(roots_seen),
        "matches": matches[:total_limit],
        "total_count": len(matches[:total_limit]),
        "truncated": truncated or len(matches) > total_limit,
        "errors": _dedupe(errors),
        "searched_at": searched_at or _now_iso(),
        "shadow_only": True,
        "probe_strategy": {
            "kind": "balanced_keyword_probe",
            "total_limit": total_limit,
            "per_pattern_limit": per_pattern_limit,
            "answer_gate_effect": "none",
        },
    }


def _normalize_source_path(path_text: str) -> str:
    text = str(path_text or "").strip().replace("\\", "/")
    text = text.replace("${domainRoot}", str(DISPATCH_ROOT))
    try:
        if text.startswith("/"):
            return str(Path(text).resolve()).replace("\\", "/").lower()
    except OSError:
        pass
    return text.rstrip("/").lower()


def _display_source_path(path_text: str) -> str:
    normalized = str(path_text or "").strip().replace("\\", "/")
    root = str(DISPATCH_ROOT)
    if normalized.startswith(root + "/"):
        return "${domainRoot}" + normalized[len(root):]
    return normalized


def _module_hit_from_catalog(module: dict[str, Any]) -> ModuleHit:
    return ModuleHit(
        module_id=str(module.get("id") or module.get("module_id") or ""),
        name=str(module.get("name") or ""),
        score=0.0,
        matched_fields=[],
        reasons=["module introduced by source_search path match"],
        solution_group=str(module.get("solution_group") or ""),
        source_paths=[str(path) for path in module.get("source_paths") or []],
    )


def _module_hits_by_id(
    run: QueryRun | None,
    module_catalog: list[dict[str, Any]] | None = None,
) -> dict[str, ModuleHit]:
    if run is None:
        result: dict[str, ModuleHit] = {}
    else:
        result = {}
        for hit in list(run.selected_modules or []) + list(run.rejected_modules or []):
            module_id = str(getattr(hit, "module_id", "") or "").strip()
            if module_id and module_id not in result:
                result[module_id] = hit
    for module in module_catalog or []:
        module_id = str(module.get("id") or module.get("module_id") or "").strip()
        if module_id and module_id not in result:
            result[module_id] = _module_hit_from_catalog(module)
    return result


def _path_matches_module_hit(path_text: str, hit: ModuleHit) -> bool:
    normalized_path = _normalize_source_path(path_text)
    for source_path in getattr(hit, "source_paths", []) or []:
        normalized_source = _normalize_source_path(str(source_path))
        if normalized_source and (
            normalized_path == normalized_source
            or normalized_path.startswith(normalized_source.rstrip("/") + "/")
        ):
            return True
    return False


def _is_test_source_path(path_text: str) -> bool:
    normalized = _normalize_source_path(path_text)
    return (
        "/test/" in normalized
        or "/tests/" in normalized
        or ".test/" in normalized
        or "tests/" in normalized
        or normalized.endswith("tests.cs")
    )


def _first_probe_match_for_module(
    source_result: dict[str, Any] | None,
    hit: ModuleHit,
) -> dict[str, Any] | None:
    if not source_result:
        return None
    include_sql = bool((source_result.get("search_contract") or {}).get("include_sql"))
    for match in source_result.get("matches") or []:
        path_text = str(match.get("path") or "")
        normalized = _normalize_source_path(path_text)
        if _is_test_source_path(path_text):
            continue
        if normalized.endswith(".sql") and not include_sql:
            continue
        if _path_matches_module_hit(path_text, hit):
            return match
    return None


def _build_soft_influence_item(
    *,
    question: str,
    candidate: dict[str, Any],
    hit: ModuleHit,
    match: dict[str, Any],
) -> dict[str, Any]:
    file_path = _display_source_path(str(match.get("path") or ""))
    line_number = int(match.get("line") or 1)
    return {
        "repo_id": str(getattr(hit, "solution_group", "") or getattr(hit, "module_id", "").split(".")[0]),
        "module_id": str(candidate.get("module_id") or getattr(hit, "module_id", "")),
        "file_path": file_path,
        "focus_symbols": [],
        "line_hints": [{"start_line": line_number, "end_line": line_number}],
        "reason": "RRF soft influence reserved one extraction slot from keyword source_search",
        "priority": 3,
        "intent_score": 1,
        "intent_trace": {
            "score": 1,
            "matched_query_tokens": [str(match.get("pattern") or "")],
            "source_search_rank": candidate.get("ranks", {}).get("source_search"),
            "rrf_score": candidate.get("rrf_score"),
            "match_line": match.get("line"),
        },
        "source": "rrf_soft_influence",
        "question": question,
    }


def _first_liftable_plan_item(
    plan: list[dict[str, Any]],
    *,
    module_id: str,
    active_limit: int,
    include_sql: bool,
) -> dict[str, Any] | None:
    for item in plan[active_limit:]:
        if str(item.get("module_id") or "") != module_id:
            continue
        file_path = str(item.get("file_path") or "")
        normalized = _normalize_source_path(file_path)
        if _is_test_source_path(file_path):
            continue
        if normalized.endswith(".sql") and not include_sql:
            continue
        return item
    return None


def _build_soft_influence_item_from_plan(
    *,
    question: str,
    candidate: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    soft_item = dict(item)
    original_trace = soft_item.get("intent_trace") if isinstance(soft_item.get("intent_trace"), dict) else {}
    soft_item["source"] = "rrf_soft_influence"
    soft_item["question"] = question
    soft_item["reason"] = (
        "RRF soft influence reserved one extraction slot by lifting an existing extraction_plan item"
    )
    soft_item["intent_trace"] = {
        **original_trace,
        "source_search_rank": candidate.get("ranks", {}).get("source_search"),
        "rrf_score": candidate.get("rrf_score"),
        "lifted_from_extraction_plan": True,
    }
    return soft_item


def apply_rrf_soft_influence(
    *,
    wiki_root: Path,
    run: QueryRun | None,
    question: str,
    hybrid_ranking: dict[str, Any],
    source_result: dict[str, Any] | None,
    module_catalog: list[dict[str, Any]] | None,
    extract_limit: int,
) -> dict[str, Any]:
    if run is None:
        return {"enabled": False, "applied": False, "reason": "no graph run"}
    if not _env_flag("LLM_WIKI_RRF_SOFT_INFLUENCE_ENABLED", "1"):
        return {"enabled": False, "applied": False, "reason": "disabled by env"}
    if extract_limit < 4:
        return {"enabled": True, "applied": False, "reason": "extract_limit below 4"}
    if not source_result or not source_result.get("matches"):
        return {"enabled": True, "applied": False, "reason": "no keyword probe matches"}

    plan = list(run.extraction_plan or [])
    if not plan:
        return {"enabled": True, "applied": False, "reason": "no extraction plan"}

    active_limit = max(1, min(extract_limit, len(plan)))
    planned_modules = {str(item.get("module_id") or "") for item in plan[:active_limit]}
    active_planned_files = {
        _normalize_source_path(str(item.get("file_path") or "")) for item in plan[:active_limit]
    }
    include_sql = bool((source_result.get("search_contract") or {}).get("include_sql"))
    hits_by_id = _module_hits_by_id(run, module_catalog=module_catalog)

    candidates = [
        candidate
        for candidate in hybrid_ranking.get("candidates") or []
        if "source_search" in (candidate.get("sources") or [])
        and (
            int(candidate.get("rank") or 999) <= 3
            or int((candidate.get("ranks") or {}).get("source_search") or 999) <= 3
        )
    ]
    candidates.sort(
        key=lambda item: (
            int((item.get("ranks") or {}).get("source_search") or 999),
            int(item.get("rank") or 999),
        )
    )

    for candidate in candidates:
        module_id = str(candidate.get("module_id") or "")
        if module_id in planned_modules:
            continue
        hit = hits_by_id.get(module_id)
        if hit is None:
            continue
        match = _first_probe_match_for_module(source_result, hit)
        if match is not None and _normalize_source_path(str(match.get("path") or "")) not in active_planned_files:
            soft_item = _build_soft_influence_item(
                question=question,
                candidate=candidate,
                hit=hit,
                match=match,
            )
            source_pattern = match.get("pattern")
            lift_source = "source_search_match"
        elif "extraction_plan" in (candidate.get("sources") or []):
            plan_item = _first_liftable_plan_item(
                plan,
                module_id=module_id,
                active_limit=active_limit,
                include_sql=include_sql,
            )
            if plan_item is None:
                continue
            soft_item = _build_soft_influence_item_from_plan(
                question=question,
                candidate=candidate,
                item=plan_item,
            )
            source_pattern = None
            lift_source = "extraction_plan_fallback"
        else:
            continue

        insert_at = max(0, active_limit - 1)
        augmented_plan = plan[:insert_at] + [soft_item] + plan[insert_at:]
        run.extraction_plan = augmented_plan
        run.direct_evidence = run_extraction(wiki_root, augmented_plan, extract_limit)
        run.evidence_sufficiency = evidence_sufficiency(
            question,
            run.semantic_intake,
            run.selected_modules,
            run.symbol_hints,
            run.community_hits,
            augmented_plan,
            run.direct_evidence,
            False,
        )
        run.trace.append(
            {
                "step": "rrf_soft_influence_extract",
                "module_id": module_id,
                "file_path": soft_item["file_path"],
                "inserted_at": insert_at + 1,
                "extract_limit": extract_limit,
                "source_pattern": source_pattern,
                "lift_source": lift_source,
            }
        )
        return {
            "enabled": True,
            "applied": True,
            "module_id": module_id,
            "file_path": soft_item["file_path"],
            "inserted_at": insert_at + 1,
            "source_pattern": source_pattern,
            "lift_source": lift_source,
        }

    return {"enabled": True, "applied": False, "reason": "no eligible RRF source_search candidate"}


def _safe_source_file(path_text: str) -> Path | None:
    try:
        path = Path(path_text).resolve()
        root = DISPATCH_ROOT.resolve()
    except OSError:
        return None
    if not path.exists() or not path.is_file():
        return None
    if path == root or root in path.parents:
        return path
    return None


def read_verify_contexts(matches: list[dict[str, Any]], *, before: int = 8, after: int = 28, limit: int = 6) -> dict[str, Any]:
    contexts: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[tuple[str, int]] = set()
    for match in matches:
        if len(contexts) >= limit:
            break
        path_text = str(match.get("path") or "")
        line_number = int(match.get("line") or 0)
        key = (path_text, line_number)
        if key in seen:
            continue
        seen.add(key)
        path = _safe_source_file(path_text)
        if path is None or line_number <= 0:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            errors.append(f"failed to read {path}: {exc}")
            continue
        start = max(1, line_number - before)
        end = min(len(lines), line_number + after)
        snippet = [
            {
                "line": index,
                "text": lines[index - 1],
            }
            for index in range(start, end + 1)
        ]
        contexts.append(
            {
                "path": str(path),
                "matched_line": line_number,
                "start_line": start,
                "end_line": end,
                "pattern": match.get("pattern"),
                "snippet": snippet,
            }
        )
    return {
        "step": "read_verify",
        "status": "completed" if contexts else "no_contexts_read",
        "contexts": contexts,
        "errors": errors,
    }


def annotate_read_verify_support(
    read_verify: dict[str, Any],
    identifiers: list[str],
    values: list[str],
) -> dict[str, Any]:
    supporting_contexts: list[dict[str, Any]] = []
    for context in read_verify.get("contexts") or []:
        text = "\n".join(str(line.get("text") or "") for line in context.get("snippet") or [])
        lowered = text.lower()
        identifier_hits = [term for term in identifiers if term.lower() in lowered]
        value_hits = [
            value
            for value in values
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])", text)
        ]
        identifier_ok = not identifiers or bool(identifier_hits)
        value_ok = not values or len(value_hits) == len(values)
        if identifier_ok and value_ok:
            supporting_contexts.append(
                {
                    "path": context.get("path"),
                    "start_line": context.get("start_line"),
                    "end_line": context.get("end_line"),
                    "identifier_hits": identifier_hits,
                    "value_hits": value_hits,
                }
            )
    read_verify["supporting_contexts"] = supporting_contexts
    return read_verify


def run_answer_gate(
    *,
    evidence_gate: dict[str, Any],
    ambiguity_gate: dict[str, Any],
    coverage: dict[str, Any],
    source_result: dict[str, Any] | None,
    read_verify: dict[str, Any] | None,
    identifiers: list[str],
    values: list[str],
) -> dict[str, Any]:
    if ambiguity_gate.get("needs_user_clarification"):
        return {
            "step": "answer_gate",
            "status": "needs_user_clarification",
            "can_answer": False,
            "user_message": ambiguity_gate.get("message"),
            "instruction": "Ask the user the clarification question. Do not keep searching or guess.",
        }
    if evidence_gate.get("can_answer_from_graph") and not coverage.get("missing_high_signal_terms"):
        return {
            "step": "answer_gate",
            "status": "can_answer_from_graph_evidence",
            "can_answer": True,
            "instruction": "Answer only from direct_evidence and cite file/symbol/line when available.",
        }
    if evidence_gate.get("can_answer_from_graph"):
        if source_result and int(source_result.get("total_count") or 0) > 0:
            context_count = len((read_verify or {}).get("contexts") or [])
            supporting_count = len((read_verify or {}).get("supporting_contexts") or [])
            if context_count and (not (identifiers or values) or supporting_count):
                return {
                    "step": "answer_gate",
                    "status": "can_answer_from_source_search",
                    "can_answer": True,
                    "missing_high_signal_terms": coverage.get("missing_high_signal_terms") or [],
                    "instruction": (
                        "Graph evidence is useful but misses some high-signal wording; use verified source_search/read_verify snippets with direct_evidence."
                    ),
                }
        return {
            "step": "answer_gate",
            "status": "needs_semantic_expansion",
            "can_answer": False,
            "missing_high_signal_terms": coverage.get("missing_high_signal_terms") or [],
            "instruction": (
                "Graph evidence is structurally useful, but it does not cover the user's high-signal wording. "
                "The outer Hermes LLM should generate search hypotheses and verify them with source_search."
            ),
        }
    if source_result and int(source_result.get("total_count") or 0) > 0:
        context_count = len((read_verify or {}).get("contexts") or [])
        supporting_count = len((read_verify or {}).get("supporting_contexts") or [])
        if (identifiers or values) and not supporting_count:
            return {
                "step": "answer_gate",
                "status": "partial_source_matches_only",
                "can_answer": False,
                "instruction": (
                    "Source matches exist, but read_verify did not find one context containing the requested identifier/value evidence together."
                ),
            }
        return {
            "step": "answer_gate",
            "status": "can_answer_from_source_search" if context_count else "partial_source_matches_only",
            "can_answer": bool(context_count),
            "instruction": (
                "Use read_verify snippets as fact evidence; if snippets do not contain the needed enum/value/API detail, answer only the found part."
            ),
        }
    if source_result is None:
        return {
            "step": "answer_gate",
            "status": "needs_semantic_expansion",
            "can_answer": False,
            "missing_high_signal_terms": coverage.get("missing_high_signal_terms") or [],
            "instruction": (
                "Do not answer yet. The outer Hermes LLM should read coverage/candidate_sources, generate 2-5 "
                "source-search hypotheses, and run deterministic source_search one hypothesis at a time."
            ),
        }
    searched_roots = (source_result or {}).get("roots") or []
    searched_patterns = (source_result or {}).get("patterns") or []
    return {
        "step": "answer_gate",
        "status": "not_found_after_verified_search",
        "can_answer": False,
        "user_message": "目前找不到直接證據。",
        "searched_roots": searched_roots,
        "searched_patterns": searched_patterns,
        "instruction": "Report a normal no-evidence answer with searched roots and keywords; do not expose guardrail/tool-loop wording.",
    }


def decision_state(answer_gate: dict[str, Any], evidence_gate: dict[str, Any], coverage: dict[str, Any]) -> dict[str, str]:
    status = str(answer_gate.get("status") or "")
    if status == "can_answer_from_graph_evidence":
        return {
            "decision": "answer_from_graph",
            "why": "graph runtime direct evidence covers the required exact or high-signal terms",
        }
    if status == "can_answer_from_source_search":
        return {
            "decision": "answer_from_verified_search",
            "why": "deterministic source_search/read_verify found fact-grade source evidence",
        }
    if status == "needs_user_clarification":
        return {
            "decision": "needs_user_clarification",
            "why": str(answer_gate.get("instruction") or "multiple plausible directions need user scope"),
        }
    if status == "not_found_after_verified_search":
        return {
            "decision": "not_found_after_verified_search",
            "why": "verified deterministic source search found no direct evidence",
        }
    missing = coverage.get("missing_high_signal_terms") or coverage.get("missing_terms") or []
    if evidence_gate.get("can_answer_from_graph") and missing:
        why = f"graph evidence exists, but direct evidence does not cover: {', '.join(str(item) for item in missing[:5])}"
    else:
        why = "graph evidence is insufficient or only provides routing candidates; outer semantic expansion is required"
    return {"decision": "needs_semantic_expansion", "why": why}


def semantic_expansion_contract() -> dict[str, Any]:
    return {
        "when": "decision=needs_semantic_expansion",
        "agent_instruction": (
            "Hermes outer LLM must generate 2-5 search hypotheses from the user question, graph evidence, "
            "coverage.missing_* terms, and candidate_sources. Do not use hardcoded business alias tables. "
            "Run source_search for one hypothesis at a time with a first-pass limit of 20, then judge the returned "
            "matches/read-verify snippets. Refine broad/common patterns before expanding to 80. "
            "Stop after at most 3 rounds or as soon as evidence is fact-grade."
        ),
        "hypothesis_schema": {
            "hypothesis": "semantic assumption to verify",
            "reason": "why this follows from the question and current evidence",
            "patterns": ["fixed-string pattern for source_search; no regex pipe"],
            "roots": ["optional root under /home/tedhsu/DispatchRawdata"],
            "stop_when": "what evidence would prove or disprove this hypothesis",
        },
        "tool": (
            "cd \"/home/tedhsu/.hermes/data/llm-wiki\" && "
            "/home/tedhsu/.hermes/hermes-agent/venv/bin/python "
            "-m llm_wiki_forge source-search --wiki-root . --pattern \"<pattern>\" --limit 20 --json"
        ),
    }


def orchestrate_query(wiki_root: Path, question: str, *, top: int = 5, extract_limit: int = 4) -> dict[str, Any]:
    wiki_root = wiki_root.resolve()
    intake = semantic_intake(question)
    graph_error: str | None = None
    evidence_pack_error: str | None = None
    run: QueryRun | None = None
    evidence_pack: Path | None = None
    module_catalog: list[dict[str, Any]] = []
    try:
        module_catalog = load_modules(wiki_root)
    except Exception:  # noqa: BLE001 - RRF can still work with graph-selected modules only.
        module_catalog = []
    try:
        run = build_query_run_graph(wiki_root, question, top, extract=True, extract_limit=extract_limit)
    except Exception as exc:  # noqa: BLE001 - orchestrator should degrade into deterministic source search.
        graph_error = f"{type(exc).__name__}: {exc}"

    identifiers = exact_identifiers(question)
    scope_roots, scope_labels = explicit_scope_roots(question)
    values = queried_values(question)
    evidence_gate = run_evidence_gate(run, identifiers, values)
    coverage = build_coverage(run, question, identifiers, values)
    candidates = candidate_sources(run, coverage)
    ambiguity_gate = run_ambiguity_gate(question, intake, run, evidence_gate, coverage, scope_labels)

    patterns = source_patterns(question, intake, identifiers)
    rrf_keyword_patterns = shadow_keyword_patterns(
        question,
        intake,
        identifiers,
        values,
        limit=_env_int("LLM_WIKI_RRF_KEYWORD_PATTERN_LIMIT", 6, minimum=1, maximum=12),
    )
    source_result: dict[str, Any] | None = None
    hybrid_keyword_probe: dict[str, Any] | None = None
    read_verify: dict[str, Any] | None = None
    should_run_verified_search = (
        not ambiguity_gate.get("needs_user_clarification")
        and not evidence_gate.get("can_answer_from_graph")
        and bool(patterns)
    )
    if should_run_verified_search:
        source_result = search_source(
            wiki_root=wiki_root,
            query=question,
            patterns=patterns,
            roots=scope_roots or None,
            limit=20,
            regex=False,
        )
        read_verify = read_verify_contexts(source_result.get("matches") or [])
        read_verify = annotate_read_verify_support(read_verify, identifiers, values)

    rrf_enabled = _env_flag("LLM_WIKI_RRF_ENABLED", "1")
    rrf_shadow = _env_flag("LLM_WIKI_RRF_SHADOW", "1")
    rrf_keyword_probe_enabled = _env_flag("LLM_WIKI_RRF_KEYWORD_PROBE_ENABLED", "1")
    if rrf_enabled and rrf_keyword_probe_enabled:
        hybrid_keyword_probe = source_result or run_shadow_keyword_probe(
            wiki_root=wiki_root,
            question=question,
            patterns=rrf_keyword_patterns,
            roots=scope_roots or None,
            total_limit=_env_int("LLM_WIKI_RRF_KEYWORD_PROBE_LIMIT", 12, minimum=1, maximum=80),
            per_pattern_limit=_env_int("LLM_WIKI_RRF_KEYWORD_PER_PATTERN_LIMIT", 3, minimum=1, maximum=20),
        )

    hybrid_ranking = build_shadow_hybrid_ranking(
        run,
        source_result=hybrid_keyword_probe,
        module_catalog=module_catalog,
        enabled=rrf_enabled,
        shadow=rrf_shadow,
    )
    rrf_soft_influence = apply_rrf_soft_influence(
        wiki_root=wiki_root,
        run=run,
        question=question,
        hybrid_ranking=hybrid_ranking,
        source_result=hybrid_keyword_probe,
        module_catalog=module_catalog,
        extract_limit=extract_limit,
    )
    if rrf_soft_influence.get("applied"):
        hybrid_ranking = build_shadow_hybrid_ranking(
            run,
            source_result=hybrid_keyword_probe,
            module_catalog=module_catalog,
            enabled=rrf_enabled,
            shadow=rrf_shadow,
        )
        hybrid_ranking["soft_influence"] = rrf_soft_influence
        evidence_gate = run_evidence_gate(run, identifiers, values)
        coverage = build_coverage(run, question, identifiers, values)
        candidates = candidate_sources(run, coverage)
        ambiguity_gate = run_ambiguity_gate(question, intake, run, evidence_gate, coverage, scope_labels)
    else:
        hybrid_ranking["soft_influence"] = rrf_soft_influence

    answer_gate = run_answer_gate(
        evidence_gate=evidence_gate,
        ambiguity_gate=ambiguity_gate,
        coverage=coverage,
        source_result=source_result,
        read_verify=read_verify,
        identifiers=identifiers,
        values=values,
    )
    state = decision_state(answer_gate, evidence_gate, coverage)

    if run is not None:
        run.hybrid_ranking = hybrid_ranking
        try:
            evidence_pack = save_query_run(run)
        except Exception as exc:  # noqa: BLE001 - evidence pack persistence should not change the answer gate.
            evidence_pack_error = f"{type(exc).__name__}: {exc}"

    graph_status = {
        "status": "ok" if run is not None else "failed",
        "error": graph_error,
        "evidence_pack_error": evidence_pack_error,
        "evidence_pack": str(evidence_pack) if evidence_pack else None,
        "direct_evidence_count": len(run.direct_evidence if run else []),
        "useful_direct_evidence_count": _useful_direct_count(run),
        "selected_module_count": len(run.selected_modules if run else []),
        "challenge_passed": run.passed_challenge() if run else False,
    }

    return {
        "question": question,
        "generated_at": _now_iso(),
        "flow": FLOW,
        "decision": state["decision"],
        "why": state["why"],
        "graph_status": graph_status,
        "coverage": coverage,
        "candidate_sources": candidates,
        "semantic_expansion_contract": semantic_expansion_contract()
        if state["decision"] == "needs_semantic_expansion"
        else None,
        "semantic_intake": intake,
        "hybrid_ranking": hybrid_ranking,
        "graph_runtime": {
            "status": graph_status["status"],
            "error": graph_error,
            "evidence_pack_error": evidence_pack_error,
            "evidence_pack": graph_status["evidence_pack"],
            "selected_modules": selected_module_summaries(run),
            "semantic_routing": (run.semantic_route if run else {}) or {},
            "semantic_evidence_sufficiency": (run.evidence_sufficiency if run else {}) or {},
            "direct_evidence_count": graph_status["direct_evidence_count"],
            "challenge_passed": graph_status["challenge_passed"],
        },
        "evidence_gate": evidence_gate,
        "ambiguity_gate": ambiguity_gate,
        "source_search": source_result,
        "hybrid_keyword_probe": {
            "patterns": (hybrid_keyword_probe.get("patterns") if hybrid_keyword_probe else []) or [],
            "total_count": hybrid_keyword_probe.get("total_count") if hybrid_keyword_probe else 0,
            "truncated": bool(hybrid_keyword_probe.get("truncated")) if hybrid_keyword_probe else False,
            "shadow_only": bool(hybrid_keyword_probe.get("shadow_only")) if hybrid_keyword_probe else False,
            "probe_strategy": hybrid_keyword_probe.get("probe_strategy") if hybrid_keyword_probe else None,
        },
        "rrf_soft_influence": rrf_soft_influence,
        "read_verify": read_verify,
        "answer_gate": answer_gate,
    }


def _print_human(result: dict[str, Any]) -> None:
    print(f"question: {result['question']}")
    print(f"flow: {' -> '.join(result['flow'])}")
    print(f"graph_runtime: {result['graph_runtime']['status']}")
    if result["graph_runtime"].get("evidence_pack"):
        print(f"evidence_pack: {result['graph_runtime']['evidence_pack']}")
    print(f"semantic_type: {result['semantic_intake'].get('question_type')}")
    print(f"evidence_gate: {result['evidence_gate'].get('status')}")
    print(f"ambiguity_gate: clarify={result['ambiguity_gate'].get('needs_user_clarification')}")
    if result["ambiguity_gate"].get("needs_user_clarification"):
        print(result["ambiguity_gate"].get("message"))
    if result.get("source_search"):
        print(f"source_search_matches: {result['source_search'].get('total_count')}")
    print(f"answer_gate: {result['answer_gate'].get('status')}")
    print(f"decision: {result.get('decision')}")
    print(f"why: {result.get('why')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes LLM Wiki query orchestrator")
    parser.add_argument("--wiki-root", default=".", help="Path to llm-wiki root")
    parser.add_argument("--question", required=True, help="User question")
    parser.add_argument("--top", type=int, default=5, help="Max module candidates")
    parser.add_argument("--extract-limit", type=int, default=4, help="Max planned files to extract")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args(argv)

    result = orchestrate_query(
        Path(args.wiki_root),
        args.question,
        top=max(1, min(args.top, 20)),
        extract_limit=max(1, min(args.extract_limit, 20)),
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
