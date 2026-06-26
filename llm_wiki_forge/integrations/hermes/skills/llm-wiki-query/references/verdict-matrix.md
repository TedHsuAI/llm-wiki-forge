# Verdict Matrix

Use this matrix when PASS/PARTIAL/FAIL is ambiguous.

## PASS

- Scope/module artifacts exist and point to the expected repo.
- Module Markdown contains inline responsibility, boundary, and routing semantics.
- Symbol hints or extraction seeds point to exact files/symbols.
- Community files are graph-backed or explicitly degraded with `source` / `degraded`.
- Semantic query smoke has `semantic.intake`, `semantic.routing`, and `semantic.evidence_sufficiency`.
- Responsibility smoke selects the target module.
- Implementation smoke has direct source evidence when `can_answer=true`.
- Graph/classic evals pass when runtime/shared pipeline changed.

## PARTIAL

- Query runtime cannot run because of local dependencies, but static artifacts look healthy.
- Responsibility smoke passes but implementation smoke lacks direct evidence.
- Communities are degraded but explicit and non-stale.
- Evals were not run because the mode is quick and runtime was not changed.
- Search found evidence, but session logs show some repeated search attempts that did not affect the final answer.

## FAIL

- Target module is missing.
- Generated module page is generic and lacks semantic routing material.
- Query routes only to unrelated modules.
- `semantic.evidence_sufficiency.status=weak` for the main smoke question.
- Stale communities are silently reused after Graphify is missing.
- Implementation answer claims are made without direct source evidence.
- Eval regression appears after runtime/shared pipeline changes.
- Agent repeats identical `search_files` calls after `BLOCKED` until guardrail stops it.

## Follow-Up Skill

- New repo absent: `llm-wiki-module-onboarding`
- Existing single repo quality gap: `llm-wiki-repo-infra-backfill`
- Shared generator/runtime/schema gap: `llm-wiki-pipeline-hardening`
- Freshness/master drift: `llm-wiki-master-sync`
- Ambiguous answering path: `llm-wiki-query-semantic-workflow`
