from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
    trace: list[dict[str, Any]] = field(default_factory=list)

    def passed_challenge(self) -> bool:
        return not any(f.severity == "error" for f in self.challenge_findings)

    def to_dict(self) -> dict[str, Any]:
        return {
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
