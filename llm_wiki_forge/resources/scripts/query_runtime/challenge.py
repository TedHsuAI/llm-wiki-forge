from __future__ import annotations

from pathlib import Path

from .code_provider import _path_from_wiki_metadata
from .models import ChallengeFinding, QueryRun


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
        if graph_path and not _path_from_wiki_metadata(str(graph_path), run.wiki_root).exists():
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
