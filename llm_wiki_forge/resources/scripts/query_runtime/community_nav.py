from __future__ import annotations

from typing import Any

from .models import ModuleHit
from .router import flatten_text, tokenize


COMMUNITY_FIELD_WEIGHTS = {
    "title": 6.0,
    "core_symbols": 4.0,
    "source_files": 2.5,
    "summary": 1.0,
}


def score_community(question_tokens: list[str], community: dict[str, Any]) -> tuple[float, list[str], list[str]]:
    score = 0.0
    matched_fields: list[str] = []
    reasons: list[str] = []
    for field, weight in COMMUNITY_FIELD_WEIGHTS.items():
        haystack = flatten_text(community.get(field)).lower()
        if not haystack:
            continue
        hits = sorted({token for token in question_tokens if token and token in haystack})
        if not hits:
            continue
        score += len(hits) * weight
        matched_fields.append(field)
        reasons.append(f"{field} matched: {', '.join(hits[:8])}")

    # Prefer larger / more connected communities only after semantic match.
    if score > 0:
        score += min(float(community.get("node_count") or 0) / 500.0, 1.5)
        score += min(float(community.get("edge_touch_count") or 0) / 1000.0, 1.5)
    return score, matched_fields, reasons


def find_community_hits(
    question: str,
    communities: list[dict[str, Any]],
    selected_modules: list[ModuleHit],
    per_module: int = 3,
) -> list[dict[str, Any]]:
    tokens = tokenize(question)
    selected_ids = {module.module_id for module in selected_modules}
    hits: list[dict[str, Any]] = []

    for community in communities:
        if community.get("module_id") not in selected_ids:
            continue
        score, matched_fields, reasons = score_community(tokens, community)
        if score <= 0:
            continue
        hits.append(
            {
                "id": community.get("id"),
                "module_id": community.get("module_id"),
                "module_name": community.get("module_name"),
                "community_id": community.get("community_id"),
                "title": community.get("title"),
                "score": round(score, 4),
                "matched_fields": matched_fields,
                "reasons": reasons,
                "core_symbols": community.get("core_symbols") or [],
                "source_files": community.get("source_files") or [],
                "risk_notes": community.get("risk_notes") or [],
                "confidence": community.get("confidence"),
            }
        )

    hits.sort(key=lambda item: item["score"], reverse=True)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for hit in hits:
        grouped.setdefault(str(hit["module_id"]), []).append(hit)

    selected: list[dict[str, Any]] = []
    for module in selected_modules:
        selected.extend(grouped.get(module.module_id, [])[:per_module])
    selected.sort(key=lambda item: item["score"], reverse=True)
    return selected

