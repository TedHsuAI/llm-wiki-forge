---
name: llm-wiki-integrity-validate
description: Run read-only LLM Wiki integrity, safety, and regression validation before or after onboarding, repo backfill, pipeline hardening, or source sync. Use when the user asks whether a wiki is safe, whether a change broke LLM Wiki, wants verification only, or wants stale community, overlay, symbol, query evidence, and sync-state checks. This skill must not modify files, accept baselines, rebuild artifacts unless explicitly requested, or repair problems.
---

# LLM Wiki Integrity Validate

Use this as the independent safety gate for an existing LLM Wiki. It validates that the wiki can still route, navigate, extract, and answer from evidence after another workflow runs.

## Portable Execution Contract

This skill is read-only by default and must not assume fixed local paths.

Required before running validation:

- `wiki_root`
- `python_command`

Optional:

- `target_repo` or `module_name`
- `mode`: `quick`, `focused`, or `full`
- `smoke_questions`

If `wiki_root` is missing and the current directory contains `wiki.scope.json`, infer it and state the assumption. If `wiki_root` is missing, ask the user and stop. If `python_command` is missing, auto-detect or create a wiki `.venv` using the `llm-wiki-build` Python Auto-Detection rule.

Run commands from `wiki_root`. Prefer Python entrypoints. If the local toolkit exposes different module names, inspect `scripts/` and use the local Python equivalent.

## Safety Contract

Do not:

- edit `wiki.scope.json`
- accept sync baselines
- hand-edit generated module/community/query JSON
- delete stale files
- start backfill/hardening repairs

If validation finds a problem, report the failure and route the fix to the correct skill.

## Modes

- `quick`: broad safety check after a small change.
- `focused`: validate one repo after onboarding/backfill/hardening.
- `full`: validate shared generator/runtime/sync changes.

## Validation Flow

### 1. Static Structure Check

From `wiki_root`, verify:

```text
wiki.scope.json
scripts/
Wiki/_data/modules
Wiki/01_Modules
Wiki/_data/query_runs
```

For focused mode, verify the target module appears in:

```bash
rg -n "<module_or_repo>|<source_path_fragment>" "<wiki_root>/Wiki/_data/modules" "<wiki_root>/Wiki/01_Modules"
```

### 2. Generated Artifact Quality

Inspect target or recent module artifacts for:

- semantic card or equivalent business context
- inline overlay semantics in module Markdown when overlays exist
- ownership, non-ownership, boundaries, or durable intake/overlay source
- entry points, route surface, or extraction seeds
- source paths that point to real repo paths visible in this environment
- no obvious vendor/cache dominance in module metadata

Fail if the module is only a generic summary and cannot support semantic routing.

### 3. Community Safety

Inspect communities for the target module or recent rebuild:

```bash
rg -n "<module_or_repo>|source|degraded|skip_reason|no_graph|jquery|Sizzle|bootstrap|\\.min\\.js|node_modules|\\bbin\\b|\\bobj\\b" "<wiki_root>/Wiki/_data/communities"
```

Passing behavior:

- graph-backed communities exist, or
- explicit degraded fallback communities exist with `source` and `degraded`

Failing behavior:

- graph/community dependency is missing and old stale communities are silently reused
- vendor/generated files dominate top navigation
- query-side community hits hide `source` / `degraded`

### 4. Semantic Query Smoke

Run at least one responsibility smoke in focused mode:

```bash
<python_command> -m scripts.query_runtime.graph_runtime --wiki-root "<wiki_root>" --question "<module_name> 的主要責任是什麼？" --top 5 --extract --extract-limit 4
```

Open the newest evidence pack under:

```text
<wiki_root>/Wiki/_data/query_runs/
```

Required evidence, using local field names when the toolkit differs:

- semantic intake or question type
- routing decision and ambiguity
- evidence sufficiency status
- whether direct source evidence is present for implementation claims
- selected/rejected module rationale when available

Passing behavior:

- responsibility questions are strong or have clear direct/module evidence
- implementation questions only claim answerability when exact source evidence exists
- plan sources prefer symbol hints when symbol metadata exists
- challenge findings do not contain unresolved semantic-route or weak-evidence warnings

### 5. Eval Regression

For quick mode, evals are optional unless query runtime changed.

For full mode or runtime/shared pipeline changes, run the local Python eval entrypoint when available:

```bash
<python_command> -m scripts.query_runtime.eval_queries --wiki-root "<wiki_root>" --runtime graph
<python_command> -m scripts.query_runtime.eval_queries --wiki-root "<wiki_root>" --runtime classic
```

If eval dependencies are missing, report `PARTIAL` or `FAIL` depending on risk. Do not claim PASS for a skipped required eval.

### 6. Search Loop Safety

Inspect recent query evidence or session logs only when a user reported a loop. The answer should state whether the agent repeated identical searches after blocked or zero-result warnings.

If repeated identical searches happened, this validation is `PARTIAL` or `FAIL` even if the final answer was usable.

## Verdict Rules

Return `PASS` only when:

- required artifacts exist
- target module routes correctly
- semantic query smoke has usable evidence
- communities are graph-backed or explicitly degraded
- no unresolved stale community, overlay-inline, or search-loop problem is found

Return `PARTIAL` when:

- structure is present, but implementation evidence is weak
- environment dependencies block query runtime
- only responsibility smoke passes
- non-critical evals were not run and the scope is clearly limited

Return `FAIL` when:

- target module is missing
- query routes to unrelated modules only
- semantic evidence sufficiency is weak for the core smoke question
- stale communities are silently reused
- query runtime or evals fail after a shared runtime change

## Handoff

- Use `llm-wiki-module-onboarding` when a new repo was never added.
- Use `llm-wiki-repo-infra-backfill` when one existing repo needs repair.
- Use `llm-wiki-pipeline-hardening` when the failure is shared generator/schema/runtime behavior.
- Use `llm-wiki-master-sync` when source freshness or master/head drift is the issue.

## Report Format

Report in Traditional Chinese:

```text
Verdict: PASS | PARTIAL | FAIL
Mode:
Wiki root:
Python command:
Target:
Commands:
Evidence packs:
Checks:
- scope/module:
- overlay/module markdown:
- symbols/extraction seeds:
- communities:
- query smoke:
- eval:
- sync state:
Handoff:
```

When uncertain, read `references/verdict-matrix.md`.
