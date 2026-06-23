---
name: llm-wiki-bootstrap
description: Create a portable first-run LLM Wiki environment when the user only has a source repo or when the selected wiki root is missing core infrastructure. Use before llm-wiki-module-onboarding when wiki.scope.json, Wiki folders, scripts, or Python entrypoints do not exist. Always state the repo path, selected wiki root, resolved Python command, and bootstrap script path before creating files. The skill must not assume fixed machine paths; if repo path is missing ask for it, if Python is missing auto-detect/create a venv or ask the user to install Python, and if wiki root is missing derive a visible default from the repo path or ask the user.
---

# LLM Wiki Bootstrap

Use this skill as step 0 for teams that do not already have an LLM Wiki root. It creates a minimal, portable LLM Wiki toolkit scaffold that `llm-wiki-module-onboarding` can use next.

## When To Use

Use this skill when:

- the user only has a C#/.NET repo and no LLM Wiki yet
- the requested `wiki_root` does not exist
- `wiki_root` exists but lacks `wiki.scope.json`, `Wiki/`, or `scripts/`
- onboarding fails because the target wiki has no base infrastructure

Do not use this skill to replace a healthy existing LLM Wiki. If `wiki_root` already has `wiki.scope.json`, `Wiki/`, and `scripts/`, report the paths and hand off to `llm-wiki-module-onboarding`.

## Path Rule

Always state these paths before creating files:

```text
repo path:
wiki root:
python command:
bootstrap script:
```

Required:

- `repo_path`: source repo path visible to the executing environment.

Optional:

- `wiki_root`: where the LLM Wiki environment should be created.
- `project_name`: inferred from `repo_path` when missing.
- `python_command`: executable Python command or venv Python path. Usually supplied by `llm-wiki-build` after auto-detection.

If `repo_path` is missing, ask the user and stop. If `python_command` is missing, auto-detect or create it using the same order as `llm-wiki-build`: existing wiki `.venv`, common system Python commands, then create `<wiki_root>/.venv`.

If `wiki_root` is missing but `repo_path` is present, derive a visible default:

```text
<parent_of_repo>/<repo_name>-llm-wiki
```

State that derived path before creating files. If the user asked to choose a path manually, ask instead.

## Bootstrap Command

Run the bundled script from this skill with the resolved Python:

```bash
<python_command> "<skill_dir>/scripts/bootstrap_llm_wiki.py" --repo-path "<repo_path>" --wiki-root "<wiki_root>" --project-name "<project_name>" --python-command "<python_command>"
```

If the user wants an empty toolkit without a first repo, omit `--repo-path` and `--project-name`, but still provide `--wiki-root`.

## What It Creates

The bootstrap script creates:

- `wiki.scope.json`
- `requirements.txt`
- `Wiki/_data/modules`
- `Wiki/_data/symbols`
- `Wiki/_data/communities`
- `Wiki/_data/query_runs`
- `Wiki/_meta/repo_sync`
- `Wiki/_meta/master_sync_runs`
- `Wiki/01_Modules`
- `Wiki/02_Symbols`
- `Wiki/03_Communities`
- `intake/`
- `scripts/update_wiki.py`
- `scripts/generate_module_wiki.py`
- `scripts/query_runtime/community_builder.py`
- `scripts/query_runtime/graph_runtime.py`
- `scripts/query_runtime/eval_queries.py`
- `scripts/repo_sync/diff_wiki.py`

These scripts are a minimal Python-first scaffold. They are meant to let a new team produce first-pass module, symbol, community, smoke-query, and sync-state artifacts without platform-specific scripts.

## After Bootstrap

Immediately run `llm-wiki-module-onboarding` with the same paths:

```text
repo path: <repo_path>
wiki root: <wiki_root>
python command: <python_command>
project name: <project_name>
```

If bootstrap already seeded the repo in `wiki.scope.json`, onboarding should treat it as a first module to validate and strengthen, not duplicate it.

## Validation

After bootstrap, verify:

```bash
<python_command> -m scripts.update_wiki --wiki-root "<wiki_root>"
<python_command> -m scripts.generate_module_wiki --wiki-root "<wiki_root>"
<python_command> -m llm_wiki_forge community build --wiki-root "<wiki_root>" --top-per-module 10
<python_command> -m llm_wiki_forge graph --wiki-root "<wiki_root>" --question "<project_name> 的主要責任是什麼？" --top 5 --extract --extract-limit 4
```

Expected:

- scope inventory exists
- module JSON/Markdown exists
- symbol seed JSON/Markdown exists when C# files are found
- community JSON exists and is marked `degraded=true` with `source=module_derived`
- query run JSON exists

## Failure Rules

- Do not hide the chosen output path.
- Do not create files when `repo_path` is missing.
- Do not overwrite a healthy existing wiki root.
- Do not claim full semantic quality from the bootstrap scaffold alone; hand off to onboarding/backfill for stronger metadata.
