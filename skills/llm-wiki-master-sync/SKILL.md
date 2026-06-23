---
name: llm-wiki-master-sync
description: Fully update the local LLM Wiki from registered source repo changes through llm-wiki-forge, preserving repo sync state, validation gates, and baseline acceptance rules. Use when source code changed, a scheduled wiki update runs, master/head should be compared, or wiki artifacts must catch up to DispatchRawdata repos.
---

# LLM Wiki Master Sync

Use this skill for durable LLM Wiki maintenance from source git changes. Build/sync/onboarding execution is owned by `llm-wiki-forge`; do not call wiki-root maintenance scripts as the primary path.

## Canonical Local Contract

```text
source root: /home/tedhsu/DispatchRawdata
wiki root: /home/tedhsu/.hermes/data/llm-wiki
repo registry: Wiki/_meta/repo_sync/repos.json
run reports: Wiki/_meta/master_sync_runs/
python: /home/tedhsu/.hermes/hermes-agent/venv/bin/python
```

The wiki root may still contain `scripts/query_runtime` during the transitional phase. That directory is for query/runtime evidence and must not be treated as the build/sync authority.

## Primary Scheduled Command

For a registered repo, run:

```bash
/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge sync \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key "<repoKey>" \
  --accept-baseline
```

Use `--dry-run` for diagnostics and `--skip-fetch` only when intentionally avoiding network/git remote checks.

## Result Semantics

- `NO_CHANGE`: reply exactly `[SILENT]` for scheduled local deliveries.
- `UPDATED`: report `repo_key`, `tracked_branch`, `before_commit`, `after_commit`, `graphify_cleanup_removed_count`, `full_sync_report_markdown`, `diff_report_markdown`, `full_sync_status`, and `accepted_baseline`.
- `DRY_RUN`: report it as a dry run and include `before_commit`, `remote_commit`, and `sync_reason`.
- `BLOCKED`, `FETCH_FAILED`, `DIVERGED`, `UPDATE_FAILED`, `SYNC_FAILED`: summarize the failure and include any report paths present.

## Validation Gates

Baseline may be accepted only when:

- the repo is on its configured branch and has no blocking dirty changes
- fetch/ff-only update succeeds or there is no remote change
- changed files exist; zero-diff runs do not accept baseline
- Forge full sync completes module rebuild, community rebuild, overlay/eval gates where available
- the per-repo state file points to the intended repo root

If eval or query dependencies are unavailable, report the gap clearly. Do not call that a clean pass unless the user explicitly accepts the residual risk.

## Quality Checks

For impacted repos or runtime changes, inspect:

```bash
rg -n "<repo_or_module>|owns|not_owns|business_terms|misleading_terms|entry_symbols|routing_examples" \
  /home/tedhsu/.hermes/data/llm-wiki/Wiki/_data/modules \
  /home/tedhsu/.hermes/data/llm-wiki/Wiki/01_Modules

/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge graph \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --question "<repo_name> 的主要責任是什麼？" \
  --top 5 --extract --extract-limit 4
```

`llm_wiki_forge graph` is the diagnostic query fallback; do not call legacy wiki-root runtime modules directly.

## Escalation

- Use `llm-wiki-module-onboarding` when a repo is missing from `wiki.scope.json` or `repos.json`.
- Use `llm-wiki-repo-infra-backfill` when one existing repo has weak semantic/query artifacts.
- Use `llm-wiki-pipeline-hardening` when the fix belongs in shared Forge/generator/runtime logic.

Do not hand-edit generated module/community/query JSON as the durable fix.

## Safety Rules

- Do not run destructive git commands such as reset, checkout, or clean.
- Do not accept baseline on zero-diff runs.
- Do not bypass Forge with local maintenance scripts unless explicitly doing a legacy fallback diagnosis.
- Do not delete wiki-root `scripts/` until cron, skills, tools, and Forge no longer reference the remaining runtime pieces.

## Report

Report in Traditional Chinese by default:

- repo key, repo root, tracked branch
- baseline, local head, remote head
- result status and report paths
- validation/eval gaps
- whether baseline was accepted
