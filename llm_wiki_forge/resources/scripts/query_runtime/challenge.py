from __future__ import annotations

from pathlib import Path

from .code_provider import _path_from_wiki_metadata
from .io import load_json, slugify
from .models import ChallengeFinding, QueryRun


def _load_scope(wiki_root: Path) -> dict:
    scope_path = wiki_root / "wiki.scope.json"
    if not scope_path.exists():
        return {}
    try:
        return load_json(scope_path)
    except Exception:
        return {}


def _graph_shard_names(module_id: str, module_name: str, graph_path: str | None) -> list[str]:
    names: list[str] = []
    normalized = str(graph_path or "").replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    for index, part in enumerate(parts):
        if part == "shards" and index + 1 < len(parts):
            names.append(parts[index + 1])
            break
    if module_id:
        names.append(module_id.replace(".", "-"))
    if module_name:
        names.append(slugify(module_name))

    unique: list[str] = []
    for name in names:
        if name and name not in unique:
            unique.append(name)
    return unique


def _graph_json_exists(run: QueryRun, module_id: str, module_name: str, graph_path: str | None) -> bool:
    if graph_path and _path_from_wiki_metadata(str(graph_path), run.wiki_root).exists():
        return True

    scope = _load_scope(run.wiki_root)
    workspace_raw = (((scope.get("tooling") or {}).get("graphify") or {}).get("workspaceSubdir") or "").strip()
    if not workspace_raw:
        return False
    try:
        workspace = _path_from_wiki_metadata(workspace_raw, run.wiki_root)
    except ValueError:
        return False
    for shard_name in _graph_shard_names(module_id, module_name, graph_path):
        if (workspace / "shards" / shard_name / "graphify-out" / "graph.json").exists():
            return True
    return False


def challenge_query_run(run: QueryRun) -> None:
    if not run.selected_modules:
        run.challenge_findings.append(
            ChallengeFinding(
                severity="error",
                code="no-module-hit",
                message="Routing did not select any module; do not synthesize an answer.",
            )
        )
        run.open_questions.append("目前 module routing 沒有命中，需要補 hint 或改善 module metadata。")
        return

    top = run.selected_modules[0]
    if not top.matched_fields:
        run.challenge_findings.append(
            ChallengeFinding(
                severity="error",
                code="no-semantic-match",
                message="Top module has no matched wiki fields; routing cannot rely on tooling/status boosts.",
            )
        )
        return

    if top.score < 3:
        run.challenge_findings.append(
            ChallengeFinding(
                severity="warning",
                code="low-routing-score",
                message=f"Top module score is low ({top.score:.2f}); treat routing as weak evidence.",
            )
        )
        run.open_questions.append("Top module 分數偏低，回答前應回 source 或補查 graph。")

    if len(run.selected_modules) > 3:
        run.challenge_findings.append(
            ChallengeFinding(
                severity="warning",
                code="broad-routing",
                message="More than 3 modules were selected; narrow before expensive extraction.",
            )
        )

    semantic_route = run.semantic_route or {}
    if semantic_route.get("ambiguity") == "high":
        run.challenge_findings.append(
            ChallengeFinding(
                severity="warning",
                code="semantic-route-ambiguous",
                message="Semantic routing is highly ambiguous; verify planned source files or the fixed cross-repo matrix before answering.",
            )
        )
    if semantic_route.get("needs_fixed_matrix"):
        run.challenge_findings.append(
            ChallengeFinding(
                severity="warning",
                code="fixed-matrix-recommended",
                message="Question is likely cross-repo; verify TGDS.WebAPI, TGDS-Dispatch-WebAPI, DispatchRule, and CoreServers if evidence stays weak.",
            )
        )

    if run.selected_modules and not run.community_hits:
        run.challenge_findings.append(
            ChallengeFinding(
                severity="warning",
                code="no-community-hit",
                message="No community matched the routed modules; navigation cannot yet suggest source files.",
            )
        )

    for hit in run.community_hits:
        if not hit.get("matched_fields"):
            run.challenge_findings.append(
                ChallengeFinding(
                    severity="error",
                    code="community-no-semantic-match",
                    message=f"Community hit has no matched fields: {hit.get('id')}",
                )
            )

    if len(run.extraction_plan) > 8:
        run.challenge_findings.append(
            ChallengeFinding(
                severity="warning",
                code="broad-extraction-plan",
                message="Extraction plan has more than 8 files; narrow before source reading.",
            )
        )

    if run.community_hits and not run.extraction_plan:
        run.challenge_findings.append(
            ChallengeFinding(
                severity="warning",
                code="no-extraction-plan",
                message="Community hits did not produce candidate source files.",
            )
        )

    for hit in run.selected_modules:
        for source_path in hit.source_paths:
            if not _path_from_wiki_metadata(source_path, run.wiki_root).exists():
                run.challenge_findings.append(
                    ChallengeFinding(
                        severity="warning",
                        code="source-path-missing",
                        message=f"Source path does not exist locally: {source_path}",
                    )
                )
        graph_path = hit.graphify.get("graph_json_path")
        if graph_path and not _graph_json_exists(run, hit.module_id, hit.name, str(graph_path)):
            run.challenge_findings.append(
                ChallengeFinding(
                    severity="warning",
                    code="graph-path-missing",
                    message=f"Graphify graph path does not exist locally: {graph_path}",
                )
            )

    if not run.direct_evidence:
        run.challenge_findings.append(
            ChallengeFinding(
                severity="warning",
                code="no-direct-evidence",
                message="P0 routing produced module evidence only; source-code logic still requires extraction.",
            )
        )
    else:
        for evidence in run.direct_evidence:
            if evidence.get("kind") == "extraction-error":
                run.challenge_findings.append(
                    ChallengeFinding(
                        severity="warning",
                        code="extraction-error",
                        message=f"Extraction failed for {evidence.get('file_path')}: {evidence.get('error')}",
                    )
                )
                continue
            start = int(evidence.get("start_line") or 0)
            end = int(evidence.get("end_line") or 0)
            if end > start and end - start > 300:
                run.challenge_findings.append(
                    ChallengeFinding(
                        severity="warning",
                        code="large-code-block",
                        message=(
                            f"Extracted block is large ({end - start + 1} lines) for "
                            f"{evidence.get('symbol') or evidence.get('file_path')}; prefer method-level extraction."
                        ),
                    )
                )
            if evidence.get("kind") == "class":
                run.challenge_findings.append(
                    ChallengeFinding(
                        severity="warning",
                        code="class-level-extraction",
                        message=(
                            f"Extracted class-level evidence for {evidence.get('symbol')}; "
                            "logic questions should narrow to methods in the next pass."
                        ),
                    )
                )

    sufficiency = run.evidence_sufficiency or {}
    if sufficiency.get("status") == "weak":
        run.challenge_findings.append(
            ChallengeFinding(
                severity="warning",
                code="weak-evidence-sufficiency",
                message=f"Semantic evidence sufficiency is weak; next step is {sufficiency.get('next_step')}.",
            )
        )
    elif sufficiency.get("status") == "partial" and sufficiency.get("needs_more_evidence"):
        run.challenge_findings.append(
            ChallengeFinding(
                severity="warning",
                code="partial-evidence-sufficiency",
                message=f"Semantic evidence sufficiency is partial; next step is {sufficiency.get('next_step')}.",
            )
        )
