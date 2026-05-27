---
name: llm-wiki-pipeline-hardening
description: Promote successful single-repo LLM Wiki onboarding or backfill findings into shared generator, schema, runtime, or validation pipeline fixes. Use after a one-repo run passes but reveals reusable gaps such as overlay semantics not being inlined, symbol-first extraction needing to become general policy, community fallback needing degraded metadata, routing/evidence trace regressions, or skills/docs needing alignment. The skill must not assume fixed paths; ask for wiki root, evidence repo, and backfill evidence when missing; auto-detect or create Python when missing.
---

# LLM Wiki Pipeline Hardening

Use this skill when one repo has proven a useful fix and the next step is to harden the shared LLM Wiki pipeline so future repos inherit it.

Keep this infrastructure-first: module JSON/Markdown, overlays, symbol hints, community navigation, query runtime, evidence packs, evals, and sync behavior.

## Portable Execution Contract

Required before mutation:

- `wiki_root`
- `evidence_repo`
- `backfill_summary` or concrete before/after evidence
- `python_command`

Optional:

- `generalization_target`

If `wiki_root` is missing and the current directory contains `wiki.scope.json`, infer it and state the assumption. If no backfill evidence is available, first run or request `llm-wiki-repo-infra-backfill` output for one repo.

Run commands from `wiki_root`. Prefer Python entrypoints. If the local toolkit uses different module names, inspect `scripts/` and use the equivalent Python entrypoint.

## Workflow

### 1. Classify The Backfill Findings

Turn the completed repo result into shared pipeline gaps. Use `references/hardening-patterns.md` for classification.

Common findings:

- Overlay content is referenced but not inlined into module JSON/Markdown.
- Extraction plan prefers lookup-table/community artifacts even when high-confidence symbol hints exist.
- Community builder skips when graph communities are unavailable and does not create a degraded-but-usable fallback.
- Routing score improved only through hand-maintained repo hints.
- Query runs pass for one repo, but the behavior is not encoded as a reusable generator/runtime rule.

Define one change set at a time. Prefer the smallest shared fix that future repos can reuse.

### 2. Snapshot Evidence Before Editing

Record current artifacts:

```bash
rg -n "<evidence_repo>|symbol_hint|lookup-table|overlay|no_graph|community" "<wiki_root>/scripts" "<wiki_root>/Wiki/_data" "<wiki_root>/Wiki/01_Modules"
<python_command> "<skill_dir>/scripts/compare_query_runs.py" --wiki-root "<wiki_root>" --repo "<evidence_repo>"
```

If the query-run comparison cannot infer exact scores or plans, manually inspect the named query-run JSON files from the backfill summary.

### 3. Inspect Existing Pipeline Boundaries

Find the local implementation before editing:

```bash
rg -n "overlay|semantic|business_context|entry_points|route_surface" "<wiki_root>/scripts"
rg -n "symbol_hint|community|extraction_plan|selected_modules|routing|score" "<wiki_root>/scripts"
rg -n "graph|no_graph|skip_reason|communities" "<wiki_root>/scripts"
```

Use existing scripts and schema conventions. Do not create a parallel generator or runtime.

### 4. Implement Shared Fixes

Pick the relevant hardening pattern:

- **Overlay inline**: merge curated overlay fields into module JSON and render them in module Markdown.
- **Symbol-first planner**: make extraction planning prefer high-confidence symbol hints and entry symbols before community lookup artifacts.
- **Community fallback**: when graph communities are missing, generate symbol-derived or module-derived fallback communities with explicit `source` and `degraded` markers.
- **Evidence/run trace**: persist selected/rejected modules, route score explanation, extraction plan source, fallback reason, direct evidence, and convergence status in query-run JSON.
- **Zero-diff behavior**: preserve no-op semantics for sync flows; do not rebuild/eval/accept baseline on empty diff.

Write tests or smoke checks at the changed layer when the repo has a local test pattern.

### 5. Rebuild The Evidence Repo

Run the smallest Python rebuild path that exercises the shared fix. Typical commands:

```bash
<python_command> -m scripts.generate_module_wiki --wiki-root "<wiki_root>"
<python_command> -m scripts.query_runtime.community_builder --wiki-root "<wiki_root>" --top-per-module 10
<python_command> -m scripts.query_runtime.graph_runtime --wiki-root "<wiki_root>" --question "<evidence_repo> 的主要責任是什麼？" --top 5 --extract --extract-limit 4
<python_command> -m scripts.query_runtime.graph_runtime --wiki-root "<wiki_root>" --question "<evidence_repo> 有哪些主要入口點？" --top 5 --extract --extract-limit 4
```

Validate:

- Smoke questions remain PASS.
- Routing score does not regress from known-good evidence unless evidence quality improves.
- Extraction plan reaches exact symbols/files, not only lookup-table communities.
- Module Markdown shows overlay-derived semantics inline when targeted.
- Community output is explicitly graph-backed or explicitly degraded fallback.

### 6. Prove It Is Not Repo-Specific

If `generalization_target` is supplied, run a small smoke loop for that repo. Otherwise choose one lightweight already-onboarded repo only when safe and obvious.

The hardening succeeds only when the second repo benefits without repo-specific names or conditions in shared code.

### 7. Align Skills And Docs

When shared behavior changes, update related skill wording in the same package:

- `llm-wiki-repo-infra-backfill` if per-repo workflow should check the new behavior.
- `llm-wiki-module-onboarding` if new repos should produce strengthened metadata by default.
- `llm-wiki-master-sync` if the invariant must survive future sync.
- README only when setup or usage instructions changed.

### 8. Report

Report in Traditional Chinese:

- source repo/backfill finding that triggered the hardening
- shared files changed
- before/after query-run paths and score/plan/evidence differences
- whether overlay inline, symbol-first, community fallback, or evidence trace behavior is now shared
- regression commands and results
- remaining generator/schema/runtime gaps

## Failure Rules

- Do not turn one repo's result into hard-coded repo-specific logic in shared pipeline files.
- Do not continue to multiple repos before the evidence repo passes again.
- Do not claim community navigation is fixed if the builder only skipped and reused old JSON.
- Do not hand-edit generated JSON/Markdown as the only fix for a generator/schema problem.
- Do not run destructive git commands.
