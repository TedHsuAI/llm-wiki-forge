---
name: llm-wiki-master-sync
description: Refresh an existing local LLM Wiki from source repo git changes by comparing the recorded baseline to a target ref, rebuilding impacted module/community/query infrastructure, running quality gates, and updating sync state only after validation passes. Use when the user says source changed, wants to update LLM Wiki from latest code, compare differences, refresh relationships, or preserve onboarding/backfill quality after code changes. The skill must not assume fixed local paths; ask for wiki root, repo path, state path, and target ref when missing; auto-detect or create Python when missing.
---

# LLM Wiki Master Sync

Use this skill for durable LLM Wiki maintenance from source repo diffs. Keep derived SA/SD/AC documents out of this flow unless the user explicitly asks for them.

## Portable Execution Contract

Required before mutation:

- `wiki_root`
- `repo_path`
- `repo_name`
- `python_command`
- `target_ref`, default `HEAD` when the user does not specify

If `wiki_root` is missing and the current directory contains `wiki.scope.json`, you may infer it and state the assumption. If `repo_path` or `wiki_root` is missing, ask the user and stop. If `python_command` is missing, auto-detect or create a wiki `.venv` using the `llm-wiki-build` Python Auto-Detection rule.

Run commands from `wiki_root`. Prefer Python entrypoints. If the local toolkit uses different module names, inspect `scripts/` and use the equivalent Python entrypoint. Do not switch to platform-specific scripts unless the user explicitly approves.

## Workspace Inputs

Use user-provided paths:

```text
wiki root: <wiki_root>
repo root: <repo_path>
sync state: <wiki_root>/Wiki/_meta/repo_sync/<repo_name>.json
run reports: <wiki_root>/Wiki/_meta/master_sync_runs/
```

Do not hard-code machine-specific roots inside generated metadata.

## Primary Workflow

### 1. Diff Preview

Run the toolkit's Python diff entrypoint, for example:

```bash
<python_command> -m scripts.repo_sync.diff_wiki --wiki-root "<wiki_root>" --repo-root "<repo_path>" --state "Wiki/_meta/repo_sync/<repo_name>.json" --target-ref "<target_ref>"
```

If the repo has no state file, treat this as first-time sync state initialization and only accept baseline after quality gates pass.

### 2. Zero-Diff Behavior

When changed file count is zero:

- write or report `completed-noop`
- do not rebuild wiki artifacts
- do not run evals
- do not accept baseline
- do not start backfill/hardening unless the user explicitly asked for diagnostics

### 3. Rebuild Impacted Artifacts

When changes exist, run the smallest Python rebuild path that refreshes impacted module metadata. Example:

```bash
<python_command> -m scripts.generate_module_wiki --wiki-root "<wiki_root>"
```

Then rebuild community navigation:

```bash
<python_command> -m scripts.query_runtime.community_builder --wiki-root "<wiki_root>" --top-per-module 10
```

If a required Python entrypoint is missing, report the missing capability and stop instead of silently running an unrelated pipeline.

### 4. Apply Durable Overlays

If the wiki uses curated overlays or intake metadata, verify overlay-derived semantic routing content appears in generated module JSON/Markdown where the generator supports it.

Do not make generated JSON the only copy of durable routing knowledge.

### 5. Eval And Quality Gates

For runtime or shared-pipeline changes, run local Python evals when available:

```bash
<python_command> -m scripts.query_runtime.eval_queries --wiki-root "<wiki_root>" --runtime graph
<python_command> -m scripts.query_runtime.eval_queries --wiki-root "<wiki_root>" --runtime classic
```

If eval dependencies are missing, report the environment gap and ask whether the user accepts the residual risk before baseline acceptance.

### 6. Targeted Smoke For Impacted Repos

For impacted repos/modules, run:

```bash
<python_command> -m scripts.query_runtime.graph_runtime --wiki-root "<wiki_root>" --question "<repo_name> 的主要責任是什麼？" --top 5 --extract --extract-limit 4
<python_command> -m scripts.query_runtime.graph_runtime --wiki-root "<wiki_root>" --question "<repo_name> 有哪些主要入口點？" --top 5 --extract --extract-limit 4
```

Passing conditions:

- intended module is selected for matching questions
- implementation questions cite exact files/symbols, not only generic module/community text
- query-run JSON preserves route score, extraction plan source, fallback reason, and direct evidence when available
- known hardened behavior does not regress

### 7. Baseline Acceptance

Accept baseline only when:

- changed files exist
- rebuild/eval/smoke gates succeeded or the user explicitly accepted a documented residual risk
- sync state points to the intended repo path

Use the toolkit's Python sync entrypoint, for example:

```bash
<python_command> -m scripts.repo_sync.diff_wiki --wiki-root "<wiki_root>" --repo-root "<repo_path>" --state "Wiki/_meta/repo_sync/<repo_name>.json" --target-ref "<target_ref>" --accept-baseline
```

## Quality Gates

### Module And Overlay Gate

```bash
rg -n "<repo_or_module>|owns|not_owns|business_terms|misleading_terms|entry_symbols|routing_examples" "<wiki_root>/Wiki/_data/modules" "<wiki_root>/Wiki/01_Modules"
```

Passing:

- Module JSON and Markdown exist for impacted repos/modules.
- Curated overlay semantics are reflected in generated module Markdown.
- Module Markdown does not regress to generic summary text.
- Generated paths are portable for the user's chosen environment.

### Symbol And Extraction Gate

```bash
rg -n "<repo_or_module>|<entry_symbol>" "<wiki_root>/Wiki/_data/symbols" "<wiki_root>/Wiki/02_Symbols" "<wiki_root>/Wiki/_data/modules"
```

Passing:

- High-value entry symbols survive rebuilds.
- Query planning can still prefer symbol hints or exact entry symbols.
- Method-level readiness is not claimed from generic summaries alone.

### Community Gate

```bash
rg -n "<repo_or_module>|source|degraded|skip_reason|jquery|Sizzle|bootstrap|\\.min\\.js|node_modules|\\bbin\\b|\\bobj\\b" "<wiki_root>/Wiki/_data/communities"
```

Passing:

- Community JSON is freshly generated for impacted modules.
- If graph data is missing, fallback communities are explicit and marked with `source` / `degraded`.
- Old stale community JSON is not silently reused.
- Top communities are not dominated by vendor/generated noise.

## Escalation Rule

Use related skills when sync exposes a quality gap:

- `llm-wiki-repo-infra-backfill`: one already-onboarded repo needs semantic card, symbol, community, or smoke-query repair.
- `llm-wiki-pipeline-hardening`: a repo-specific repair reveals a shared generator/schema/runtime issue.
- `llm-wiki-module-onboarding`: the repo is missing from `wiki.scope.json` / inventory and must be added first.

Do not solve shared generator/runtime problems by hand-editing generated JSON/Markdown only.

## Safety Rules

- Do not pull, reset, checkout, or clean source branches unless the user explicitly asks.
- Do not accept baseline on zero-diff runs.
- Do not accept baseline while required eval or quality gates are failing unless the user explicitly accepts the residual risk.
- Use skip switches only for diagnostics when the local toolkit supports them.

## Report

Report in Traditional Chinese:

- wiki root, repo path, repo name, Python command
- target ref and baseline
- changed file count
- rebuilt artifacts
- eval/smoke results
- sync state path
- whether baseline was accepted
- residual risks or follow-up skill
