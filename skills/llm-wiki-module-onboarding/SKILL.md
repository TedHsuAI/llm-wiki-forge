---
name: llm-wiki-module-onboarding
description: Add a new DispatchRawdata source repo into the local LLM Wiki through llm-wiki-forge repo add, then validate generated module artifacts, query readiness, and per-repo sync state. Use when the user puts a new repo under DispatchRawdata and asks AI to import/build/add it to the LLM Wiki.
---

# LLM Wiki Module Onboarding

Use this skill when a repo should be explicitly added to the shared local LLM Wiki. The implementation entrypoint is `llm-wiki-forge`; do not edit `wiki.scope.json` by hand unless repairing a failed Forge run.

## Canonical Local Contract

```text
source root: /home/tedhsu/DispatchRawdata
wiki root: /home/tedhsu/.hermes/data/llm-wiki
repo registry: Wiki/_meta/repo_sync/repos.json
python: /home/tedhsu/.hermes/hermes-agent/venv/bin/python
```

The user flow is explicit: the user puts a repo under `DispatchRawdata`, then asks AI to onboard that repo. Do not auto-discover and import arbitrary new directories.

## Required Inputs

- `repo`: folder name under `/home/tedhsu/DispatchRawdata` or an absolute path under that root
- `repo_key`: stable registry key; default to repo folder name
- `wiki_path`: target module logical name; default to `repo_key`
- `tracked_branch`: default to the repo's current branch
- `schedule`: optional cron expression
- at least one smoke question when the user has a known query scenario

## Primary Command

```bash
/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge repo add \
  --repo /home/tedhsu/DispatchRawdata/<RepoName> \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key "<repoKey>" \
  --wiki-path "<wikiPath>"
```

Add `--schedule "<cron>"` only when the repo should also be registered for future scheduled sync. Add `--no-build` only for a registry-only repair.

## What Forge Must Do

- validate repo path stays under `/home/tedhsu/DispatchRawdata`
- update exactly one repo entry in `wiki.scope.json`
- update exactly one repo entry in `Wiki/_meta/repo_sync/repos.json`
- run scope/module/community/query validation unless `--no-build` is supplied
- initialize `Wiki/_meta/repo_sync/<repoKey>.json` for git-backed repos
- leave query runtime under `scripts/query_runtime` untouched during phase one

## Validation Gates

Onboarding is complete only when:

- scope inventory includes the repo and excludes `.git`, `.vs`, `bin`, `obj`, `node_modules`, packages, and test output
- module JSON and Markdown exist for the repo
- generated metadata describes this repo, not a neighboring TGDS/Dispatch module
- important entry files/symbols are discoverable or a generator gap is reported
- community navigation is fresh or explicitly degraded
- smoke query evidence selects the intended module for responsibility questions
- implementation questions have direct source evidence before claiming a code fact
- per-repo sync state exists when the source is git-backed

## Failure Rules

- Stop after a failed Forge command; inspect stdout/stderr and report the failed gate.
- Do not add path hacks outside `DispatchRawdata`.
- Do not hand-edit generated JSON/Markdown as the only durable fix.
- Do not initialize or accept baseline before smoke evidence is acceptable unless the user explicitly accepts the risk.

## Report

Report in Traditional Chinese by default:

- repo key and source path
- wiki root and target wiki path
- files changed by Forge
- generated module paths
- smoke query verdict
- sync state path
- any residual generator/query-runtime gaps
