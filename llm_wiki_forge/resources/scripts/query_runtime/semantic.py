from __future__ import annotations

from typing import Any

from .models import ModuleHit
from .router import tokenize


USEFUL_EVIDENCE_KINDS = {"method", "method-chunk", "class", "enum", "property", "line-window", "file"}


QUESTION_PATTERNS: list[tuple[str, list[str]]] = [
    (
        "fare_formula",
        [
            "固定車資",
            "預估車資",
            "車資",
            "計算公式",
            "fare",
            "price",
            "quotation",
            "taxifarecalc",
            "taxiplusv2",
        ],
    ),
    (
        "dispatch_rule",
        [
            "dispatchrule",
            "dispatch rule",
            "派車規則",
            "regufilter",
            "rulemonkey",
            "路由",
            "分流",
            "dispatch",
        ],
    ),
    (
        "api_flow",
        [
            "api",
            "controller",
            "endpoint",
            "request",
            "response",
            "入口點",
            "呼叫流程",
            "路由",
        ],
    ),
    (
        "data_writeback",
        [
            "寫入",
            "更新",
            "db",
            "database",
            "table",
            "repository",
            "insert",
            "update",
            "writeback",
        ],
    ),
    (
        "impact_analysis",
        [
            "影響",
            "impact",
            "風險",
            "改動",
            "變更",
            "會不會",
            "哪些地方",
            "相關",
        ],
    ),
    (
        "route_map",
        [
            "路線圖",
            "畫圖",
            "google routes",
            "directions",
            "polyline",
            "directionjson",
            "地圖",
        ],
    ),
    (
        "payment",
        [
            "付款",
            "金流",
            "小費",
            "tip",
            "payment",
            "bill",
            "charge",
        ],
    ),
    (
        "address_geocoding",
        [
            "地址",
            "英文地址",
            "geocode",
            "geocoding",
            "gps",
            "經緯度",
            "google map",
        ],
    ),
]


CODE_TERM_PATTERNS: list[tuple[str, list[str]]] = [
    ("controller", ["api", "controller", "endpoint", "route", "入口點"]),
    ("service", ["service", "服務", "邏輯", "計算"]),
    ("repository", ["repository", "db", "database", "table", "資料庫", "寫入"]),
    ("filter", ["filter", "regufilter", "規則", "過濾"]),
    ("worker", ["worker", "job", "排程", "batch", "批次"]),
    ("dto-model", ["request", "response", "dto", "model", "參數", "欄位"]),
]


def _contains_any(question_lower: str, tokens: set[str], phrases: list[str]) -> list[str]:
    hits: list[str] = []
    for phrase in phrases:
        candidate = phrase.lower()
        if candidate in question_lower or candidate in tokens:
            hits.append(phrase)
    return hits


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


def semantic_intake(question: str) -> dict[str, Any]:
    question_lower = question.lower()
    tokens = set(tokenize(question))
    matched_types: list[dict[str, Any]] = []
    for question_type, phrases in QUESTION_PATTERNS:
        hits = _contains_any(question_lower, tokens, phrases)
        if hits:
            matched_types.append({"question_type": question_type, "matched_terms": hits, "score": len(hits)})
    matched_types.sort(key=lambda item: int(item["score"]), reverse=True)

    question_type = matched_types[0]["question_type"] if matched_types else "unknown"
    business_terms = _dedupe([term for item in matched_types for term in item["matched_terms"]])
    code_terms: list[str] = []
    for label, phrases in CODE_TERM_PATTERNS:
        if _contains_any(question_lower, tokens, phrases):
            code_terms.append(label)

    requires_code_evidence = question_type not in {"unknown"} or bool(code_terms)
    cross_repo_likely = question_type in {"dispatch_rule", "impact_analysis", "payment", "route_map"}
    if {"dispatch", "派車", "搜車", "車資", "payment", "付款", "api"} & tokens:
        cross_repo_likely = True

    must_answer_by_type = {
        "fare_formula": [
            "formula entry point",
            "calculation method",
            "input fields and business conditions",
            "source file and method evidence",
        ],
        "dispatch_rule": [
            "routing responsibility",
            "entry symbol or filter",
            "boundary of what should not route here",
            "source file and method evidence",
        ],
        "api_flow": [
            "API/controller entry point",
            "request/response or DTO shape when present",
            "call chain to service/repository",
            "source file and method evidence",
        ],
        "data_writeback": [
            "write location",
            "repository/table or stored procedure when present",
            "transaction or side effect",
            "source file and method evidence",
        ],
        "impact_analysis": [
            "affected modules",
            "direct callers/callees",
            "risk boundaries",
            "source file and method evidence",
        ],
        "route_map": [
            "route/direction source",
            "conversion method",
            "output field",
            "source file and method evidence",
        ],
        "payment": [
            "payment entry point",
            "fare or bill mutation",
            "external integration or repository",
            "source file and method evidence",
        ],
        "address_geocoding": [
            "parsing/geocoding entry point",
            "fallback behavior",
            "locale or validation limitation",
            "source file and method evidence",
        ],
        "unknown": [
            "best routed module",
            "why the route was selected",
            "source evidence if behavior is claimed",
        ],
    }

    not_asking_by_type = {
        "fare_formula": [
            "Do not answer from DispatchRule-only evidence when the user asks for the fare formula.",
            "Do not treat dispatch applicability as the calculation formula unless source evidence proves it.",
        ],
        "dispatch_rule": [
            "Do not explain TGDS.WebAPI API contracts unless the question asks for endpoint behavior.",
            "Do not treat stale lookup-table communities as source-code evidence.",
        ],
        "api_flow": [
            "Do not stop at module routing; identify controller/service source evidence.",
        ],
        "impact_analysis": [
            "Do not claim no impact after checking only one module.",
        ],
    }

    confidence_score = min(1.0, (sum(int(item["score"]) for item in matched_types[:3]) + len(code_terms)) / 8)
    return {
        "question_type": question_type,
        "matched_question_types": matched_types[:5],
        "business_terms": business_terms,
        "code_terms_guess": code_terms,
        "must_answer": must_answer_by_type.get(question_type, must_answer_by_type["unknown"]),
        "not_asking": not_asking_by_type.get(question_type, []),
        "routing_guardrails": [
            "Use symbol_hint/direct evidence before community-only evidence.",
            "If evidence is weak or single-module for dispatch/fare/payment, verify TGDS.WebAPI, TGDS-Dispatch-WebAPI, DispatchRule, and CoreServers before a negative answer.",
            "Treat semantic intake as a hypothesis; source code evidence wins.",
        ],
        "requires_code_evidence": requires_code_evidence,
        "cross_repo_likely": cross_repo_likely,
        "confidence": round(confidence_score, 3),
    }


def semantic_route_explanation(
    intake: dict[str, Any],
    selected_modules: list[ModuleHit],
    rejected_modules: list[ModuleHit],
) -> dict[str, Any]:
    top_candidates: list[dict[str, Any]] = []
    for hit in selected_modules[:5]:
        matched_semantic_fields = [
            field
            for field in hit.matched_fields
            if field.startswith("semantic_card") or field in {"business_tags", "business_context.summary", "technical_contract.entry_points"}
        ]
        top_candidates.append(
            {
                "module_id": hit.module_id,
                "name": hit.name,
                "score": round(hit.score, 4),
                "matched_fields": hit.matched_fields,
                "semantic_alignment": "strong" if matched_semantic_fields else "metadata-only",
                "matched_semantic_fields": matched_semantic_fields,
                "reasons": hit.reasons[:5],
            }
        )

    top_score = selected_modules[0].score if selected_modules else 0.0
    second_score = selected_modules[1].score if len(selected_modules) > 1 else 0.0
    score_delta = round(top_score - second_score, 4)
    if not selected_modules or top_score < 5:
        ambiguity = "high"
    elif len(selected_modules) > 1 and score_delta < 3:
        ambiguity = "high"
    elif len(selected_modules) > 1 and score_delta < 8:
        ambiguity = "medium"
    else:
        ambiguity = "low"

    needs_fixed_matrix = bool(intake.get("cross_repo_likely")) and (
        ambiguity != "low" or top_score < 15 or len(selected_modules) < 2
    )
    return {
        "question_type": intake.get("question_type") or "unknown",
        "top_candidates": top_candidates,
        "rejected_sample": [
            {
                "module_id": hit.module_id,
                "name": hit.name,
                "score": round(hit.score, 4),
                "reject_reason": "no positive semantic/router score",
            }
            for hit in rejected_modules[:5]
        ],
        "ambiguity": ambiguity,
        "top_score_delta": score_delta,
        "needs_fixed_matrix": needs_fixed_matrix,
        "route_decision_rule": (
            "Proceed with top symbol/direct-evidence candidates"
            if ambiguity == "low"
            else "Treat routing as provisional and verify planned files or fixed matrix"
        ),
    }


def evidence_sufficiency(
    question: str,
    intake: dict[str, Any],
    selected_modules: list[ModuleHit],
    symbol_hints: list[dict[str, Any]],
    community_hits: list[dict[str, Any]],
    extraction_plan: list[dict[str, Any]],
    direct_evidence: list[dict[str, Any]],
    fallback_attempted: bool = False,
) -> dict[str, Any]:
    del question
    useful_direct_count = sum(1 for item in direct_evidence if item.get("kind") in USEFUL_EVIDENCE_KINDS)
    extraction_errors = [item for item in direct_evidence if item.get("kind") == "extraction-error"]
    plan_sources = sorted({str(item.get("source") or "unknown") for item in extraction_plan})
    has_symbol_plan = "symbol_hint" in plan_sources
    degraded_community_count = sum(
        1
        for hit in community_hits
        if hit.get("degraded") is True or str(hit.get("source") or "").lower().startswith("degraded")
    )

    missing: list[str] = []
    if not selected_modules:
        missing.append("selected module")
    if not symbol_hints and intake.get("requires_code_evidence"):
        missing.append("symbol hint")
    if not extraction_plan and intake.get("requires_code_evidence"):
        missing.append("extraction plan")
    if useful_direct_count == 0 and intake.get("requires_code_evidence"):
        missing.append("direct source evidence")
    if degraded_community_count and not has_symbol_plan:
        missing.append("non-degraded community evidence")
    if extraction_errors and useful_direct_count == 0:
        missing.append("successful extraction")

    if not selected_modules:
        status = "weak"
    elif useful_direct_count > 0 and (has_symbol_plan or not intake.get("requires_code_evidence")):
        status = "strong"
    elif useful_direct_count > 0:
        status = "partial"
    elif symbol_hints and extraction_plan:
        status = "partial"
    elif community_hits and extraction_plan and not intake.get("requires_code_evidence"):
        status = "partial"
    else:
        status = "weak"

    can_answer = status == "strong" or (status == "partial" and not intake.get("requires_code_evidence"))
    if status == "strong":
        next_step = "answer_from_direct_evidence"
    elif not selected_modules:
        next_step = "harden_wiki_metadata"
    elif not extraction_plan:
        next_step = "expand_fixed_matrix_or_backfill_repo"
    elif useful_direct_count == 0:
        next_step = "run_extraction_or_read_planned_files"
    else:
        next_step = "answer_with_uncertainty_and_source_paths"

    return {
        "status": status,
        "can_answer": can_answer,
        "needs_more_evidence": not can_answer,
        "missing": missing,
        "next_step": next_step,
        "signals": {
            "selected_module_count": len(selected_modules),
            "symbol_hint_count": len(symbol_hints),
            "community_hit_count": len(community_hits),
            "degraded_community_count": degraded_community_count,
            "extraction_plan_count": len(extraction_plan),
            "direct_evidence_count": len(direct_evidence),
            "useful_direct_evidence_count": useful_direct_count,
            "extraction_error_count": len(extraction_errors),
            "plan_sources": plan_sources,
            "has_symbol_hint_plan": has_symbol_plan,
            "fallback_attempted": fallback_attempted,
        },
    }
