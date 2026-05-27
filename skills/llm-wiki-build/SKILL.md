---
name: llm-wiki-build
description: Primary orchestration skill for building an LLM Wiki from a repo request. Use this as the default entrypoint when the user says to build, create, generate, bootstrap, or set up an LLM Wiki for a repo. It standardizes path collection, Python environment detection/creation, infrastructure detection, bootstrap, module onboarding, focused validation, and follow-up routing. It must not assume fixed paths; it must state repo path, wiki root, and resolved Python command before creating or changing files.
---

# LLM Wiki Build

Use this as the professional top-level entrypoint for LLM Wiki creation. This skill coordinates the other skills; it should not duplicate their detailed implementation.

## Goal

Turn this kind of user request:

```text
幫我針對 <repo> 建立 LLM Wiki，wiki 路徑是 <wiki_root>
```

into one consistent department-wide flow:

```text
collect inputs -> state paths -> inspect wiki root -> bootstrap if needed -> onboarding -> validate -> report
```

## Required Inputs

Required:

- `repo_path`: source repo path visible to the executing environment.

Optional:

- `wiki_root`: desired LLM Wiki root.
- `python_command`: executable Python command or venv Python path. Usually omitted; auto-detect it.
- `project_name`: inferred from `repo_path` if missing.
- `smoke_questions`: user-provided acceptance questions.
- `known_neighbors`: repos/modules likely to be confused with this one.
- `high_value_entry_files`: controllers, services, repositories, jobs, handlers, filters, workers, or API endpoints.

If `repo_path` is missing, ask the user and stop. Do not ask normal users for `python_command` first; auto-detect or create it.

If `wiki_root` is missing, derive:

```text
<parent_of_repo>/<repo_name>-llm-wiki
```

State the derived path before any filesystem changes.

## Python Auto-Detection

If `python_command` was not supplied, resolve it in this order:

1. Existing wiki venv:
   - `<wiki_root>/.venv/bin/python`
   - `<wiki_root>/.venv/Scripts/python.exe`
2. Common commands, testing each with `--version`:
   - `python`
   - `python3`
   - `py -3`
3. If a system Python is found but no wiki venv exists, create one:

```bash
<system_python> -m venv "<wiki_root>/.venv"
```

Then set `python_command` to the venv Python path.

4. If no Python can be found, stop and ask the user to install Python 3.11+ or provide the Python executable path.

After resolving Python, run:

```bash
<python_command> --version
<python_command> -m pip install --upgrade pip
```

If `<wiki_root>/requirements.txt` exists, install it:

```bash
<python_command> -m pip install -r "<wiki_root>/requirements.txt"
```

If `requirements.txt` does not exist yet, continue; `llm-wiki-bootstrap` can create a minimal one.

## Non-Negotiable Path Announcement

Before creating or modifying project/wiki files, report:

```text
Repo path:
Wiki root:
Python command: <auto-detected or user-supplied path>
Project name:
Mode: bootstrap+onboarding | onboarding-only | validate-only
```

Do not hide defaulted or inferred paths.

## Decision Flow

### 1. Normalize Inputs

- Resolve or restate `repo_path`.
- Infer `project_name` from the repo folder name when missing.
- Resolve or derive `wiki_root`.
- Resolve `python_command` using Python Auto-Detection.

If the repo path is unreadable from the executing environment, stop and ask for the path as seen by that environment.

### 2. Inspect Wiki Root

Check whether `wiki_root` has base infrastructure:

```text
<wiki_root>/wiki.scope.json
<wiki_root>/Wiki
<wiki_root>/scripts
```

If any are missing, mode is `bootstrap+onboarding`.

If all exist, mode is `onboarding-only`.

If the user explicitly asks only to verify an existing wiki, mode is `validate-only`.

### 3. Bootstrap When Needed

If mode is `bootstrap+onboarding`, use `llm-wiki-bootstrap`.

Pass:

```text
repo_path
wiki_root
project_name
python_command
```

Bootstrap must create the base infrastructure, then run its own minimal checks. Do not treat bootstrap alone as final success.

### 4. Onboard The Repo

Use `llm-wiki-module-onboarding`.

Pass:

```text
project_name
repo_path
wiki_root
python_command
smoke_questions
known_neighbors
high_value_entry_files
```

Onboarding must run stepwise gates: scope, inventory, module artifacts, extraction seeds, community navigation, query smoke, and repo sync state when git-backed.

### 5. Validate Focused Result

After onboarding, use `llm-wiki-integrity-validate` in focused mode.

Pass:

```text
wiki_root
python_command
target_repo = project_name
mode = focused
smoke_questions
```

If validation is `PASS`, finish.

If validation is `PARTIAL`, report exact missing evidence or dependencies and whether the wiki is usable for responsibility-level questions.

If validation is `FAIL`, route:

- missing repo/module -> rerun or repair `llm-wiki-module-onboarding`
- weak single-repo semantics/symbols/community/query evidence -> `llm-wiki-repo-infra-backfill`
- shared generator/runtime/schema issue -> `llm-wiki-pipeline-hardening`
- source freshness/baseline issue -> `llm-wiki-master-sync`

### 6. Stop After One Repo

Do not continue to another repo in the same run unless the user explicitly asks. The standard build unit is one repo.

## Completion Criteria

Return `PASS` only when:

- selected paths were stated
- bootstrap was run when infrastructure was missing
- module onboarding completed
- focused validation passed
- generated artifacts exist
- smoke evidence exists

Return `PARTIAL` when:

- bootstrap and module artifacts exist, but query runtime dependencies or implementation evidence are incomplete
- responsibility smoke passes but code-level smoke lacks direct evidence
- the user accepts an environment gap for now

Return `FAIL` when:

- repo path is unreadable
- Python cannot be found or created
- bootstrap cannot create base infrastructure
- module artifacts are missing
- query/validation routes to unrelated modules only
- generated artifacts are too generic to support LLM Wiki usage

## Report Format

Report in Traditional Chinese:

```text
Verdict: PASS | PARTIAL | FAIL
Mode:
Repo:
Repo path:
Wiki root:
Python command:

Steps:
1. Input/path check:
2. Bootstrap:
3. Onboarding:
4. Focused validation:

Generated artifacts:
- Scope:
- Module JSON:
- Module Markdown:
- Symbols:
- Communities:
- Query runs:
- Repo sync state:

Smoke questions:
- ...

Next step:
```

## Related Skills

- `llm-wiki-bootstrap`: create base infrastructure.
- `llm-wiki-module-onboarding`: build the repo module.
- `llm-wiki-integrity-validate`: focused verification.
- `llm-wiki-repo-infra-backfill`: repair one existing repo.
- `llm-wiki-pipeline-hardening`: promote reusable pipeline fixes.
- `llm-wiki-master-sync`: update wiki after source changes.

## Safety Rules

- Do not infer hidden machine-specific paths.
- Do not overwrite a healthy existing wiki with bootstrap.
- Do not claim success from bootstrap alone.
- Do not skip focused validation.
- Do not run destructive git commands.
- Do not modify generated JSON as the only durable fix.
