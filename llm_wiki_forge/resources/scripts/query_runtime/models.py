from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact_hybrid_ranking(value: dict[str, Any], candidate_limit: int = 5) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}

    summary: dict[str, Any] = {}
    for key in ("enabled", "mode", "k", "candidate_unit", "applied_to_decision", "generated_at"):
        if key in value:
            summary[key] = value.get(key)

    signals: list[dict[str, Any]] = []
    for signal in value.get("signals") or []:
        if not isinstance(signal, dict):
            continue
        entry = {
            "source": signal.get("source"),
            "candidate_count": signal.get("candidate_count"),
        }
        ranked_ids = signal.get("ranked_module_ids") or []
        if ranked_ids:
            entry["ranked_module_ids"] = ranked_ids[:5]
        signals.append(entry)
    if signals:
        summary["signals"] = signals

    top_candidates: list[dict[str, Any]] = []
    for candidate in (value.get("candidates") or [])[:candidate_limit]:
        if not isinstance(candidate, dict):
            continue
        top_candidates.append(
            {
                key: candidate.get(key)
                for key in (
                    "rank",
                    "module_id",
                    "name",
                    "solution_group",
                    "rrf_score",
                    "sources",
                    "ranks",
                )
                if key in candidate
            }
        )
    if top_candidates:
        summary["top_candidates"] = top_candidates

    source_probe = value.get("source_search_probe")
    if isinstance(source_probe, dict):
        summary["source_search_probe"] = {
            key: source_probe.get(key)
            for key in (
                "query",
                "patterns",
                "total_count",
                "truncated",
                "errors",
                "shadow_only",
                "probe_strategy",
            )
            if key in source_probe
        }

    soft_influence = value.get("soft_influence")
    if isinstance(soft_influence, dict):
        summary["soft_influence"] = {
            key: soft_influence.get(key)
            for key in (
                "enabled",
                "applied",
                "reason",
                "module_id",
                "file_path",
                "inserted_at",
                "source_pattern",
                "lift_source",
            )
            if key in soft_influence
        }

    return summary


@dataclass
class ModuleHit:
    module_id: str
    name: str
    solution_group: str
    score: float
    matched_fields: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    source_paths: list[str] = field(default_factory=list)
    graphify: dict[str, Any] = field(default_factory=dict)
    confidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "name": self.name,
            "solution_group": self.solution_group,
            "score": round(self.score, 4),
            "matched_fields": self.matched_fields,
            "reasons": self.reasons,
            "source_paths": self.source_paths,
            "graphify": self.graphify,
            "confidence": self.confidence,
        }


@dataclass
class ChallengeFinding:
    severity: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


@dataclass
class QueryRun:
    question: str
    wiki_root: Path
    generated_at: str = field(default_factory=now_iso)
    selected_modules: list[ModuleHit] = field(default_factory=list)
    rejected_modules: list[ModuleHit] = field(default_factory=list)
    community_hits: list[dict[str, Any]] = field(default_factory=list)
    symbol_hints: list[dict[str, Any]] = field(default_factory=list)
    extraction_plan: list[dict[str, Any]] = field(default_factory=list)
    direct_evidence: list[dict[str, Any]] = field(default_factory=list)
    semantic_intake: dict[str, Any] = field(default_factory=dict)
    semantic_route: dict[str, Any] = field(default_factory=dict)
    evidence_sufficiency: dict[str, Any] = field(default_factory=dict)
    inference: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    challenge_findings: list[ChallengeFinding] = field(default_factory=list)
    hybrid_ranking: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)

    def passed_challenge(self) -> bool:
        return not any(f.severity == "error" for f in self.challenge_findings)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "question": self.question,
            "generated_at": self.generated_at,
            "runtime_stage": "p1_navigation_planning",
            "challenge_passed": self.passed_challenge(),
            "routing": {
                "selected_modules": [m.to_dict() for m in self.selected_modules],
                "rejected_modules": [m.to_dict() for m in self.rejected_modules],
            },
            "semantic": {
                "intake": self.semantic_intake,
                "routing": self.semantic_route,
                "evidence_sufficiency": self.evidence_sufficiency,
            },
            "navigation": {
                "community_hits": self.community_hits,
                "extraction_plan": self.extraction_plan,
            },
            "symbol_hints": self.symbol_hints,
            "synthesis_inputs": {
                "direct_evidence": self.direct_evidence,
                "inference": self.inference,
                "open_questions": self.open_questions,
            },
            "challenge": {
                "findings": [f.to_dict() for f in self.challenge_findings],
            },
            "trace": self.trace,
        }
        hybrid_ranking = compact_hybrid_ranking(self.hybrid_ranking)
        if hybrid_ranking:
            data["hybrid_ranking"] = hybrid_ranking
        return data
