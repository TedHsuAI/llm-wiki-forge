---
name: llm-wiki-module-onboarding
description: Add one source repo or project path into a local LLM Wiki as a self-validating module. Use when the user asks to create, build, import, or generate an LLM Wiki for a C#/.NET project, needs wiki.scope.json updated, or wants module metadata, symbol/extraction seeds, community navigation, query smoke evidence, and repo sync state created step by step. If the selected wiki root lacks infrastructure, use llm-wiki-bootstrap first. The skill must not assume fixed local paths; if repo path is missing, ask before mutating files; if Python is missing, auto-detect or create a wiki .venv first.
---

# LLM Wiki Module Onboarding

Use this skill to onboard one C#/.NET repo into an existing LLM Wiki. One source repo becomes one module by default unless the user explicitly requests a monorepo split.

## Portable Execution Contract

Do not assume any personal path, drive letter, platform-specific home directory, container mount, or preconfigured wiki root.

Required before mutation:

- `project_name`
- `repo_path`
- `wiki_root`
- `python_command`

Always state the selected paths before editing:

```text
repo path:
wiki root:
python command:
```

If `wiki_root` is missing and `repo_path` is present, derive a visible default path:

```text
<parent_of_repo>/<repo_name>-llm-wiki
```

State the derived path before creating files. If `project_name` is missing but `repo_path` is present, infer the final path segment and state that assumption. If `repo_path` is missing, ask the user and stop. If `python_command` is missing, auto-detect it using the `llm-wiki-build` Python Auto-Detection rule and create `<wiki_root>/.venv` when needed.

If `wiki_root` does not exist, or exists but lacks `wiki.scope.json`, `Wiki/`, or `scripts/`, use `llm-wiki-bootstrap` first. After bootstrap, continue this onboarding with the same paths.

Prefer Python entrypoints from the user's LLM Wiki toolkit. Run commands from `wiki_root`. If the local toolkit uses different Python module names than the examples below, inspect `scripts/` and use the equivalent Python entrypoint. Do not switch to platform-specific scripts unless the user explicitly says that environment supports them.

## Output Quality Contract

Onboarding is complete only when the repo can support semantic-first query and later maintenance:

- Scope inventory knows the repo and excludes generated/vendor noise.
- Module JSON/Markdown expose responsibility, boundaries, business terms, confused modules, entry files/symbols, relationships, risk, and confidence.
- Durable intake or overlay metadata exists for facts the generator cannot infer.
- Symbol hints or extraction seeds point to concrete C# files/classes/methods.
- Community navigation is graph-backed or explicitly degraded with `source` / `degraded`; stale silent reuse is not acceptable.
- Query smoke evidence includes semantic intake/routing/evidence sufficiency or the local equivalent.
- Per-repo sync state exists for git-backed repos after smoke gates pass.

## Required Inputs

Collect:

- `project_name`: stable module/source name.
- `repo_path`: existing source path visible to the executing environment.
- `wiki_root`: existing LLM Wiki root containing `wiki.scope.json`.
- `python_command`: resolved executable Python command or venv Python path; normally supplied by `llm-wiki-build` or auto-detected.
- `smoke_questions`: at least one responsibility question and preferably one entry-point or implementation question.
- `known_neighbors`: nearby repos/modules users may confuse with this repo.
- `high_value_entry_files`: controllers, services, repositories, workers, jobs, handlers, filters, or API endpoints.
- `solution_filter`: optional `.slnf` file when the Visual Studio solution intentionally unloads or hides projects.

## Preconditions

Before editing:

```text
<wiki_root>/wiki.scope.json exists
<wiki_root>/scripts exists
<repo_path> exists
<python_command> --version succeeds
```

If the first two checks fail, do not ask the user to manually create the wiki. Use `llm-wiki-bootstrap` to build the base infrastructure, then rerun these preconditions.

Also check whether Python toolkit dependencies are installed. If imports or entrypoints fail because dependencies are missing, report the missing package and stop before modifying generated artifacts.

## Workflow

### 1. Create Or Update Intake Notes

Use the wiki's existing intake/workbench convention if present. If none exists, create a repo-specific note under a clearly named intake folder inside `wiki_root`.

Record:

- project name and source path
- whole-repo module decision
- smoke questions
- what the repo owns and does not own
- common business terms and misleading terms
- confused sibling modules/repos
- high-value entry files and symbols
- negative routing examples
- environment notes: Python command, platform, optional Graphify/community dependency status
- run log with dates and gate outcomes

### 2. Update `wiki.scope.json`

Back up `wiki.scope.json` inside the wiki metadata area before editing.

Add exactly one repo entry and one target for the normal single-module case:

```json
{
  "logicalName": "<project_name>",
  "actualRoot": "<repo_path>",
  "include": true,
  "reason": "Single-module project onboarded into this LLM Wiki.",
  "targets": [
    {
      "logicalName": "<project_name>",
      "actualPath": "<repo_path>",
      "type": "project-root",
      "include": true,
      "reason": "Initial whole-repo module."
    }
  ]
}
```

Use a JSON parser or careful scoped edit. Do not rewrite unrelated repos. If the same `logicalName` or `actualRoot` already exists, confirm whether this is a repair/backfill case instead of a new onboarding.

### 3. Refresh Scope Inventory

Run the wiki toolkit's Python inventory entrypoint, for example:

```bash
<python_command> -m scripts.update_wiki --wiki-root "<wiki_root>"
```

If the toolkit exposes a different Python module, use that equivalent. Continue only after validating:

- command exit code is 0
- scope inventory mentions `project_name` or `repo_path`
- machine-readable scope inventory exists
- unrelated existing repo entries were not removed
- generated/cache directories such as `.git`, `.vs`, `bin`, `obj`, `node_modules`, `packages`, and `TestResults` were not included as source targets
- if a `.slnf` exists, `projectScopeSource` is `solution_filter` and unloaded projects are listed under `excludedProjectFiles`
- if no `.slnf` exists but `.sln` files exist, project scanning follows `.sln` project entries instead of every discovered `.csproj`

### 4. Build Module Artifacts

Run the wiki toolkit's Python module generation entrypoint, for example:

```bash
<python_command> -m scripts.generate_module_wiki --wiki-root "<wiki_root>"
```

Continue only after validating:

- module JSON exists for the project
- module Markdown exists for the project
- metadata/source paths point to `repo_path`
- generated content describes this repo, not an unrelated existing repo
- module semantics include responsibility, boundaries, business terms, entry points, dependencies, risk, and confidence
- `technicalContract.projectScopeSource`, `projectFiles`, and `excludedProjectFiles` explain which Visual Studio projects were scanned or skipped
- overlay/intake facts are visible in generated artifacts or clearly reported as a generator gap
- C# entry files/classes/methods are discoverable as symbol hints or extraction seeds

### 5. Strengthen Extraction Metadata

Identify 5-15 high-value entry files/symbols that should be read before broad search. Preserve them in durable metadata such as intake, overlay, generator input, or the wiki's semantic-card schema.

Capture:

- `owns`
- `not_owns`
- `business_terms`
- `misleading_terms`
- `confused_modules`
- `entry_symbols`
- `entry_files`
- `fast_path_questions`
- `reject_examples`
- `routing_examples`

Do not hand-edit generated JSON as the only fix if the next rebuild would erase it.

### 6. Rebuild Community Navigation

Run the Python community builder if available:

```bash
<python_command> -m scripts.query_runtime.community_builder --wiki-root "<wiki_root>" --top-per-module 10
```

If Graphify or another graph dependency is unavailable, require an explicit degraded fallback community with `source` and `degraded` metadata. Do not treat stale reused community JSON as PASS.

### 7. Run Query Smoke Tests

Use the user's smoke questions. If none were supplied, start with:

```text
<project_name> 的主要責任是什麼？
<project_name> 有哪些主要入口點？
什麼問題不應該路由到 <project_name>？
```

Run each question through the Python query runtime when available:

```bash
<python_command> -m scripts.query_runtime.graph_runtime --wiki-root "<wiki_root>" --question "<question>" --top 5 --extract --extract-limit 4
```

PASS requires the intended module to be selected for matching questions and exact source evidence for implementation questions. If dependency gaps prevent query runtime execution, report `PARTIAL` with the missing dependencies; do not mark smoke as passed.

### 8. Initialize Per-Repo Sync State

Only after scope, module, community, and smoke checks pass, initialize or verify per-repo sync state for git-backed repos using the toolkit's Python sync entrypoint, for example:

```bash
<python_command> -m scripts.repo_sync.diff_wiki --wiki-root "<wiki_root>" --repo-root "<repo_path>" --state "Wiki/_meta/repo_sync/<project_name>.json" --baseline HEAD --target-ref HEAD --accept-baseline
```

If the source is not a git repo, skip sync state and explain that incremental sync needs git metadata.

## Failure Rules

- Do not proceed after a failed validation gate.
- Do not accept or initialize baseline before smoke evidence is acceptable.
- Do not run destructive git commands.
- Do not onboard multiple repos in one run.
- Do not add path fallback hacks; fix `wiki.scope.json`, generator inputs, overlays, or metadata at the source.

## Reporting

Report in Traditional Chinese by default:

- project name, repo path, wiki root, Python command
- files changed
- commands run and gate results
- generated module JSON/Markdown paths
- symbol/extraction seed status
- community status
- smoke query evidence path and verdict
- whether per-repo sync state was initialized

For detailed validation heuristics, read `references/validation-gates.md`.
