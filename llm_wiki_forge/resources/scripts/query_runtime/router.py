from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .models import ModuleHit


STOPWORDS = {
    "的",
    "了",
    "會",
    "嗎",
    "我",
    "要",
    "在",
    "是",
    "和",
    "與",
    "及",
    "或",
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "what",
    "where",
    "which",
    "how",
}


FIELD_WEIGHTS = {
    "id": 8.0,
    "name": 8.0,
    "solution_group": 4.0,
    "business_tags": 5.0,
    "business_context.summary": 4.0,
    "skill_description": 3.5,
    "technical_contract.entry_points": 4.0,
    "technical_contract.route_surface": 4.0,
    "dependencies": 2.0,
    "callers": 2.5,
    "callees": 2.5,
    "evidence": 1.25,
    "risk_notes": 1.5,
}


DOMAIN_SYNONYMS = {
    "小費": ["tip", "tips", "fare", "payment", "bill", "price", "charge", "加價"],
    "搜車": ["dispatch", "job", "search", "rank", "派車", "叫車"],
    "派車": ["dispatch", "job", "rank", "車隊", "driver"],
    "司機": ["driver", "ive", "vehicle"],
    "車機": ["ive", "socket", "driver"],
    "訂單": ["order", "job", "booking"],
    "付款": ["payment", "bill", "fare"],
    "固定車資": [
        "taxiplusv2",
        "quotation",
        "make",
        "isfixedprice",
        "fixedprice",
        "fixedpricecards",
        "cardquotation",
        "taxiplusquotation",
        "fare",
        "price",
    ],
    "車資": ["fare", "price", "taxifarecalc", "estimatedfare", "quotation"],
    "taxiplusv2": ["taxiplusv2", "quotation", "cardquotation", "isfixedprice", "taxiplusquotation"],
    "make": ["quotation_make", "makequotation", "createquotation", "writequotation2db", "quotation"],
    "路線圖": ["directionjson", "direction", "directions", "routes", "polyline", "tripbase", "google"],
    "畫圖": ["directionjson", "direction", "directions", "routes", "polyline", "tripbase", "google"],
    "google routes": ["computeroutes", "computeroutesdirectionsadapter", "directions", "directionjson", "polyline"],
    "api": ["controller", "route", "webapi"],
    "報表": ["report", "olap"],
    "排程": ["worker", "scheduler", "job"],
    "socket": ["socket", "protocol", "ive"],
}


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    raw = re.findall(r"[A-Za-z0-9_.]+|[\u4e00-\u9fff]{2,}", lowered)
    tokens = [token for token in raw if token not in STOPWORDS]
    expanded = list(tokens)
    for phrase, synonyms in DOMAIN_SYNONYMS.items():
        if phrase in lowered:
            expanded.append(phrase)
            expanded.extend(synonyms)
    for token in tokens:
        expanded.extend(DOMAIN_SYNONYMS.get(token, []))
    return expanded


def flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(flatten_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(flatten_text(item) for item in value.values())
    return str(value)


def get_path(data: dict[str, Any], dotted: str) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def score_module(question_tokens: list[str], module: dict[str, Any]) -> ModuleHit:
    token_counts = Counter(question_tokens)
    score = 0.0
    matched_fields: list[str] = []
    reasons: list[str] = []

    for field, weight in FIELD_WEIGHTS.items():
        value = module.get(field) if "." not in field else get_path(module, field)
        haystack = flatten_text(value).lower()
        if not haystack:
            continue
        hits = [token for token in token_counts if token and token in haystack]
        if not hits:
            continue
        field_score = sum(token_counts[token] for token in hits) * weight
        score += field_score
        matched_fields.append(field)
        reasons.append(f"{field} matched: {', '.join(sorted(set(hits))[:8])}")

    graphify = module.get("graphify") or {}
    if score > 0 and graphify.get("status") == "enabled":
        score += 0.5
    if module.get("kind") == "shared-library" and {"baseclass", "shared", "共用"} & set(question_tokens):
        score += 5.0
        reasons.append("shared-library boost")

    confidence = module.get("confidence") or {}
    return ModuleHit(
        module_id=str(module.get("id") or ""),
        name=str(module.get("name") or ""),
        solution_group=str(module.get("solution_group") or ""),
        score=score,
        matched_fields=matched_fields,
        reasons=reasons,
        source_paths=[str(path) for path in module.get("source_paths") or []],
        graphify=graphify,
        confidence=confidence,
    )


def route_modules(question: str, modules: list[dict[str, Any]], top: int = 5) -> tuple[list[ModuleHit], list[ModuleHit], list[str]]:
    tokens = tokenize(question)
    hits = [score_module(tokens, module) for module in modules]
    hits.sort(key=lambda hit: hit.score, reverse=True)
    selected = [hit for hit in hits if hit.score > 0][:top]
    rejected = [hit for hit in hits if hit.score <= 0]
    return selected, rejected, tokens
