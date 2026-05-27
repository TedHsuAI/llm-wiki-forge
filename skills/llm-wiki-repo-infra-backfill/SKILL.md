---
name: llm-wiki-repo-infra-backfill
description: Backfill and validate one already-onboarded repo in an existing LLM Wiki. Use when the user wants to strengthen module semantics, symbol/extraction seeds, community navigation, routing explanations, query evidence, or per-repo sync state for a single repo. Do not use for adding a brand-new repo; use llm-wiki-module-onboarding first. The skill must not assume fixed local paths; ask for wiki root and repo name/path when missing; auto-detect or create Python when missing.
---

# LLM Wiki Repo Infra Backfill

Use this skill to improve an existing LLM Wiki one repo at a time. Keep the work infrastructure-first: scope, module metadata, semantic routing, symbol/extraction seeds, community navigation, query evidence, and sync state.

Do not batch every repo in the wiki. Finish and validate one repo, report gaps, then wait for the next repo request.

## Portable Execution Contract

Required before mutation:

- `wiki_root`
- `repo_name` or `repo_path`
- `python_command`

If `wiki_root` is missing and the current directory contains `wiki.scope.json`, you may infer it and state the assumption. If only `repo_path` is supplied, infer `repo_name` from the folder name and state it. If `wiki_root` or repo identity is missing, ask the user and stop. If `python_command` is missing, auto-detect or create a wiki `.venv` using the `llm-wiki-build` Python Auto-Detection rule.

Run commands from `wiki_root`. Prefer Python entrypoints. If the local toolkit uses different module names, inspect `scripts/` and use the local Python equivalent. Do not switch to platform-specific scripts unless the user explicitly approves.

## Required Inputs

Establish:

- `wiki_root`: existing LLM Wiki root containing `wiki.scope.json`.
- `repo_name` or `repo_path`: an already-onboarded repo/module to backfill.
- `python_command`: resolved executable Python command or venv Python path; normally auto-detected.
- `smoke_questions`: 1-3 representative user questions when available.

If the repo is not represented in `wiki.scope.json` or scope inventory, stop and use `llm-wiki-module-onboarding` instead.

## Preconditions

Verify:

```text
<wiki_root>/wiki.scope.json exists
<wiki_root>/Wiki/_data/scope.inventory.json exists
<wiki_root>/scripts exists
<python_command> --version succeeds
```

If a required Python entrypoint is missing, inspect the local toolkit and adapt to its current entrypoint. Do not invent a parallel pipeline.

## Workflow

### 1. Lock Scope To One Repo

Find the repo in current metadata:

```bash
rg -n "<repo_name>|<repo_path_fragment>" "<wiki_root>/wiki.scope.json" "<wiki_root>/Wiki/_data/scope.inventory.json" "<wiki_root>/Wiki/_data/modules"
```

Continue only after you can name the repo entry, module JSON path(s), module Markdown page(s), and source root.

### 2. Run Baseline Audit

Use the bundled audit helper when available:

```bash
<python_command> "<skill_dir>/scripts/audit_repo_infra.py" --wiki-root "<wiki_root>" --repo "<repo_name>"
```

Read `references/infra-gates.md` when the audit output is ambiguous. Treat the audit as triage, not the source of truth.

### 3. Backfill Semantic Card Source

Strengthen durable source metadata for the repo/module. Prefer updating generator inputs, curated overlays, or intake/workbench notes over hand-editing generated JSON.

Capture:

- `owns`
- `not_owns`
- `business_terms`
- `misleading_terms`
- `confused_modules`
- `upstream_downstream`
- `entry_symbols`
- `entry_files`
- `routing_examples`

If the current wiki has no formal semantic-card schema, create or update a repo-specific intake/overlay note and report the schema gap.

### 4. Improve Symbol And Extraction Seeds

Check module, symbol, and route-surface metadata:

```bash
rg -n "<repo_name>|<repo_path_fragment>|<entry_symbol>" "<wiki_root>/Wiki/_data/symbols" "<wiki_root>/Wiki/_data/modules" "<wiki_root>/Wiki/01_Modules"
```

If coverage is sparse, add durable extraction seeds through repo/module overlay or generator input. Do not claim method-level readiness from module summaries alone.

### 5. Rebuild And Inspect Module Artifacts

Run the smallest Python rebuild command that refreshes this repo's module metadata. Example:

```bash
<python_command> -m scripts.generate_module_wiki --wiki-root "<wiki_root>"
```

Validate that the repo's module JSON/Markdown still exists, that curated overlay semantics are inlined when overlays are present, and that the rebuild did not regress unrelated repo paths.

### 6. Rebuild Community Navigation

Run:

```bash
<python_command> -m scripts.query_runtime.community_builder --wiki-root "<wiki_root>" --top-per-module 10
```

Inspect repo-related communities for useful business/system clusters and vendor/generated noise. If graph/community dependencies are unavailable, require explicit degraded fallback communities with `source` / `degraded` markers instead of silently reusing stale JSON.

### 7. Run Query Evidence Smoke Tests

Use user questions first. Otherwise use:

```text
<repo_name> 的主要責任是什麼？
<repo_name> 有哪些主要入口點？
什麼問題不應該路由到 <repo_name>？
```

Run:

```bash
<python_command> -m scripts.query_runtime.graph_runtime --wiki-root "<wiki_root>" --question "<question>" --top 5 --extract --extract-limit 4
```

Open the newest `Wiki/_data/query_runs` JSON. Passing evidence needs selected/rejected module rationale when available, exact files/symbols for implementation questions, convergence after fallback, and community metadata that distinguishes graph-backed hits from degraded fallback hits.

### 8. Verify Per-Repo Sync State

Check for independent sync state under:

```text
<wiki_root>/Wiki/_meta/repo_sync/
```

If missing and the repo is a git repo, initialize it only after metadata, community, and smoke gates pass. Preserve the zero-diff rule: when diff has no changed files, do not rebuild, run eval, or accept baseline.

### 9. Report And Stop

Report in Traditional Chinese:

- repo name/path and wiki root
- Python command
- changed files and why they are durable
- baseline audit summary before/after
- module JSON/Markdown, symbol, community, and query-run paths
- smoke questions and gate results
- unresolved generator/schema gaps

Stop after one repo.

## Failure Rules

- Do not backfill every repo in one run.
- Do not mix derived SA/SD/AC documents into core wiki infrastructure work.
- Do not add runtime-only fallback hacks for broken metadata; fix `wiki.scope.json`, generator inputs, overlays, or generated metadata source.
- Do not hand-edit generated JSON as the only fix unless there is no durable source yet; if you must, record the generator gap.
- Do not accept sync baselines before smoke evidence is acceptable.
