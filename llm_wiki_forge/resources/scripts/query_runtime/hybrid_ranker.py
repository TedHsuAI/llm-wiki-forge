from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


RRF_K = 60
DOMAIN_ROOT = "/home/tedhsu/DispatchRawdata"


def rrf_score(rank: int, k: int = RRF_K) -> float:
    if rank < 1:
        raise ValueError("rank must be 1-based")
    return 1.0 / (k + rank)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_path(path_text: str) -> str:
    text = str(path_text or "").strip().replace("\\", "/")
    text = text.replace("${domainRoot}", DOMAIN_ROOT)
    try:
        if text.startswith("/"):
            return str(Path(text).resolve()).replace("\\", "/").lower()
    except OSError:
        pass
    return text.rstrip("/").lower()


def _module_lookup(run: Any, module_catalog: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    modules: dict[str, dict[str, Any]] = {}
    for hit in list(getattr(run, "selected_modules", []) or []) + list(getattr(run, "rejected_modules", []) or []):
        module_id = str(getattr(hit, "module_id", "") or "").strip()
        if not module_id or module_id in modules:
            continue
        modules[module_id] = {
            "module_id": module_id,
            "name": str(getattr(hit, "name", "") or ""),
            "solution_group": str(getattr(hit, "solution_group", "") or ""),
            "source_paths": [str(path) for path in getattr(hit, "source_paths", []) or []],
        }
    for module in module_catalog or []:
        module_id = str(module.get("id") or module.get("module_id") or "").strip()
        if not module_id or module_id in modules:
            continue
        modules[module_id] = {
            "module_id": module_id,
            "name": str(module.get("name") or ""),
            "solution_group": str(module.get("solution_group") or ""),
            "source_paths": [str(path) for path in module.get("source_paths") or []],
        }
    return modules


def _append_rank_signal(
    signals: list[dict[str, Any]],
    *,
    source: str,
    module_ids: list[str],
    raw_scores: dict[str, Any] | None = None,
) -> None:
    ranked_ids: list[str] = []
    seen: set[str] = set()
    for module_id in module_ids:
        normalized = str(module_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ranked_ids.append(normalized)
    if ranked_ids:
        signals.append(
            {
                "source": source,
                "ranked_module_ids": ranked_ids,
                "raw_scores": raw_scores or {},
            }
        )


def _router_signal(run: Any) -> tuple[list[str], dict[str, Any]]:
    ranked: list[str] = []
    raw_scores: dict[str, Any] = {}
    for hit in getattr(run, "selected_modules", []) or []:
        module_id = str(getattr(hit, "module_id", "") or "")
        if not module_id:
            continue
        ranked.append(module_id)
        raw_scores[module_id] = getattr(hit, "score", None)
    return ranked, raw_scores


def _semantic_signal(run: Any) -> tuple[list[str], dict[str, Any]]:
    route = getattr(run, "semantic_route", {}) or {}
    ranked: list[str] = []
    raw_scores: dict[str, Any] = {}
    for item in route.get("top_candidates") or []:
        module_id = str(item.get("module_id") or "")
        if not module_id:
            continue
        ranked.append(module_id)
        raw_scores[module_id] = item.get("score")
    return ranked, raw_scores


def _community_signal(run: Any) -> tuple[list[str], dict[str, Any]]:
    ranked: list[str] = []
    raw_scores: dict[str, Any] = {}
    for item in getattr(run, "community_hits", []) or []:
        module_id = str(item.get("module_id") or item.get("module") or "")
        if not module_id:
            continue
        ranked.append(module_id)
        raw_scores.setdefault(module_id, item.get("score") or item.get("rank"))
    return ranked, raw_scores


def _symbol_signal(run: Any) -> tuple[list[str], dict[str, Any]]:
    ranked: list[str] = []
    raw_scores: dict[str, Any] = {}
    for item in getattr(run, "symbol_hints", []) or []:
        module_id = str(item.get("module_id") or "")
        if not module_id:
            continue
        ranked.append(module_id)
        raw_scores.setdefault(module_id, item.get("score"))
    return ranked, raw_scores


def _extraction_plan_signal(run: Any) -> tuple[list[str], dict[str, Any]]:
    ranked: list[str] = []
    raw_scores: dict[str, Any] = {}
    for item in getattr(run, "extraction_plan", []) or []:
        module_id = str(item.get("module_id") or item.get("repo_id") or "")
        if not module_id:
            continue
        ranked.append(module_id)
        raw_scores.setdefault(module_id, item.get("intent_score"))
    return ranked, raw_scores


def _path_matches_module(match_path: str, module: dict[str, Any]) -> bool:
    normalized_match = _normalize_path(match_path)
    if not normalized_match:
        return False
    for source_path in module.get("source_paths") or []:
        normalized_source = _normalize_path(str(source_path))
        if normalized_source and (
            normalized_match == normalized_source
            or normalized_match.startswith(normalized_source.rstrip("/") + "/")
        ):
            return True
    return False


def _source_search_signal(
    run: Any,
    source_result: dict[str, Any] | None,
    module_catalog: list[dict[str, Any]] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    if not source_result:
        return [], {}
    modules = _module_lookup(run, module_catalog=module_catalog)
    ranked: list[str] = []
    raw_scores: dict[str, Any] = {}
    for index, match in enumerate(source_result.get("matches") or [], start=1):
        path = str(match.get("path") or "")
        for module_id, module in modules.items():
            if not _path_matches_module(path, module):
                continue
            ranked.append(module_id)
            raw_scores.setdefault(module_id, {"first_match_rank": index, "match_count": 0})
            raw_scores[module_id]["match_count"] += 1
            break
    return ranked, raw_scores


def merge_rank_signals(
    signals: list[dict[str, Any]],
    *,
    modules: dict[str, dict[str, Any]] | None = None,
    k: int = RRF_K,
    limit: int = 10,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for signal in signals:
        source = str(signal.get("source") or "unknown")
        for rank, module_id in enumerate(signal.get("ranked_module_ids") or [], start=1):
            if not module_id:
                continue
            entry = merged.setdefault(
                module_id,
                {
                    "module_id": module_id,
                    "rrf_score": 0.0,
                    "sources": [],
                    "ranks": {},
                },
            )
            entry["rrf_score"] += rrf_score(rank, k)
            if source not in entry["sources"]:
                entry["sources"].append(source)
            entry["ranks"].setdefault(source, rank)

    module_info = modules or {}
    sorted_entries = sorted(
        merged.values(),
        key=lambda item: (-float(item["rrf_score"]), str(item["module_id"])),
    )[:limit]
    for rank, entry in enumerate(sorted_entries, start=1):
        info = module_info.get(str(entry["module_id"])) or {}
        entry["rank"] = rank
        entry["rrf_score"] = round(float(entry["rrf_score"]), 6)
        if info.get("name"):
            entry["name"] = info["name"]
        if info.get("solution_group"):
            entry["solution_group"] = info["solution_group"]
    return sorted_entries


def build_shadow_hybrid_ranking(
    run: Any | None,
    *,
    source_result: dict[str, Any] | None = None,
    module_catalog: list[dict[str, Any]] | None = None,
    enabled: bool = True,
    shadow: bool = True,
    k: int = RRF_K,
    limit: int = 10,
) -> dict[str, Any]:
    if run is None or not enabled:
        return {
            "enabled": bool(enabled),
            "mode": "shadow" if shadow else "disabled",
            "k": k,
            "candidate_unit": "module_id",
            "applied_to_decision": False,
            "candidates": [],
            "signals": [],
            "generated_at": _now_iso(),
        }

    signals: list[dict[str, Any]] = []
    for source, builder in (
        ("router", _router_signal),
        ("semantic_route", _semantic_signal),
        ("community", _community_signal),
        ("symbol", _symbol_signal),
        ("extraction_plan", _extraction_plan_signal),
    ):
        ranked, raw_scores = builder(run)
        _append_rank_signal(signals, source=source, module_ids=ranked, raw_scores=raw_scores)

    ranked, raw_scores = _source_search_signal(run, source_result, module_catalog=module_catalog)
    _append_rank_signal(signals, source="source_search", module_ids=ranked, raw_scores=raw_scores)

    modules = _module_lookup(run, module_catalog=module_catalog)
    source_probe: dict[str, Any] | None = None
    if source_result:
        source_probe = {
            "query": source_result.get("query"),
            "patterns": (source_result.get("patterns") or [])[:10],
            "total_count": source_result.get("total_count", 0),
            "truncated": bool(source_result.get("truncated")),
            "errors": (source_result.get("errors") or [])[:5],
            "shadow_only": bool(source_result.get("shadow_only", False)),
            "probe_strategy": source_result.get("probe_strategy"),
        }
    return {
        "enabled": True,
        "mode": "shadow" if shadow else "active",
        "k": k,
        "candidate_unit": "module_id",
        "applied_to_decision": False,
        "note": "RRF-lite fuses router/semantic/navigation signals and an optional shadow keyword source_search probe; it does not change answer gates.",
        "signals": [
            {
                "source": signal["source"],
                "candidate_count": len(signal.get("ranked_module_ids") or []),
                "ranked_module_ids": (signal.get("ranked_module_ids") or [])[:10],
            }
            for signal in signals
        ],
        "source_search_probe": source_probe,
        "candidates": merge_rank_signals(signals, modules=modules, k=k, limit=limit),
        "generated_at": _now_iso(),
    }
