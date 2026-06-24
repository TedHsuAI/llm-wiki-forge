# LLM Wiki Forge

[English](README.md) | [繁體中文](README.zh-TW.md)

LLM Wiki Forge is the versioned correctness engine for a local LLM Wiki.

It owns the workflows that change or verify evidence:

- update registered source repositories
- refresh generated wiki artifacts
- query code behavior through packaged runtimes
- run deterministic source search
- validate evidence freshness and reuse
- ship canonical runtime integration packs, including Hermes

Hermes can still be the conversation layer. Forge is the source of truth for the query and maintenance behavior behind it.

Repository: <https://github.com/TedHsuAI/llm-wiki-forge>

## Supported Targets

LLM Wiki Forge currently supports two code families:

- `.NET / C#`
- `Android / Kotlin / Java`

Parsers for both families are installed by default. The `.NET / C#` pipeline is currently the most exercised path; Android support is available but should still be validated against the target repo.

## Project Layout

```text
llm_wiki_forge/
  cli.py                         # CLI commands
  workflows.py                   # update, refresh, code query orchestration
  query_adapter.py               # Hermes-compatible query/source-search payloads
  repo_sync.py                   # registered repo sync state
  runtime.py                     # packaged runtime execution
  integrations/
    hermes/                      # Forge-owned Hermes integration pack
  resources/
    bootstrap_llm_wiki.py        # bootstrap generator
    scripts/query_runtime/       # packaged query runtime modules
skills/                          # agent-facing LLM Wiki skills
tests/                           # Forge and integration tests
```

`llm_wiki_forge/integrations/hermes` is intentionally visible. It is not hidden under low-level resources because it is a public integration contract: Hermes installs runtime copies from here, while Forge keeps the versioned source.

## Responsibility Boundary

```text
Forge
  repo update -> wiki refresh -> code query -> source search -> evidence validation

Hermes
  receive user questions -> call stable tools -> organize evidence -> write human answers

Hermes integration pack
  Forge-owned copies of Hermes tools, skills, guard rules, and tests
```

The intended split is simple: Forge owns correctness; Hermes owns presentation and semantic organization.

## Current Capabilities

### Repository And Wiki Maintenance

- `update`: fetch or inspect a registered source repo, refresh wiki artifacts, run gates, and update sync state.
- `refresh`: rebuild generated wiki artifacts for one existing repo without updating git.
- `repo add`: register a source repo in `wiki.scope.json` and repo sync metadata.
- `build` / `bootstrap` / `validate`: create and validate a wiki from a source repo.

### Code Evidence Query

- `code query`: run the packaged query orchestrator and return a Hermes-compatible payload.
- `code source-search`: run deterministic fixed-string source search and return compact or full evidence.
- recent evidence pack reuse with similarity and freshness checks.
- compact result shaping for Slack-sized answers.
- full result mode for local debugging and audits.

### Hermes Integration

Forge includes the canonical Hermes integration pack:

```text
llm_wiki_forge/integrations/hermes/
  tools/llm_wiki_query.py
  tools/llm_wiki_forge.py
  skills/llm-wiki-query/SKILL.md
  hooks/slack_readonly_guard.py
  tests/test_llm_wiki_query_tool.py
  manifest.json
```

Hermes keeps runtime copies of these files because its registry and skill loader need local files. Forge owns the versioned source.

## Install

From GitHub:

```bash
python -m pip install git+https://github.com/TedHsuAI/llm-wiki-forge.git
```

For local development:

```bash
git clone https://github.com/TedHsuAI/llm-wiki-forge.git
cd llm-wiki-forge
python -m pip install -e .
```

The CLI entrypoint is:

```bash
llm-wiki --version
```

You can also run it as a Python module:

```bash
python -m llm_wiki_forge --version
```

## Requirements

- Python 3.11+
- Git
- read access to the source repos
- recommended: `rg`
- for `.NET / C#`: `.slnf`, `.sln`, and `.csproj` improve extraction scope
- for Android: Kotlin/Java parser dependencies are installed by default
- Graphify package: `graphifyy>=0.4.10,<0.9`

When a `.NET` repo contains unloaded or intentionally excluded Visual Studio projects, prefer a shared `.slnf` solution filter. Forge treats `.slnf` projects as the active project set and skips C# files outside those project roots. If no `.slnf` exists, Forge uses `.sln` project entries when available.

## CLI Quick Start

### Update A Registered Repo

Use this when source git changed and the wiki needs fresh artifacts.

```bash
llm-wiki update \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key <RepoKey>
```

Dry-run first when you only want a plan:

```bash
llm-wiki update \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key <RepoKey> \
  --dry-run
```

### Refresh Wiki Artifacts

Use this when git state is already correct and only generated artifacts need rebuilding.

```bash
llm-wiki refresh --wiki-root <wiki_root> --repo <RepoName> --json
```

### Query Code Behavior

Use this for business logic, API behavior, routing, dispatch, fare, payment, scheduler, and other codebase questions.

```bash
llm-wiki code query \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --question "搜車中加小費的相關邏輯?" \
  --top 5 \
  --extract-limit 4 \
  --json
```

The JSON payload includes:

- `decision`
- `next_action`
- `routing.selected_modules`
- `direct_evidence`
- `direct_evidence_count`
- `evidence_pack`
- `reuse_decision`
- `freshness_status`
- `source_search`

When `next_action` is `run_source_search`, use deterministic source search.

```bash
llm-wiki code source-search \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --pattern SearchTipEligibilityService \
  --limit 20 \
  --json
```

### Add A Repo To A Multi-Repo Wiki

```bash
llm-wiki repo add \
  --repo /home/tedhsu/DispatchRawdata/<RepoName> \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key <RepoKey> \
  --wiki-path <WikiPath>
```

### Build A New Wiki

```bash
llm-wiki build --repo <repo_path> --wiki-root <wiki_root>
```

If `--wiki-root` is omitted, Forge defaults to:

```text
<repo_parent>/<repo_name>-llm-wiki
```

## Hermes Integration

Install the Forge-owned Hermes integration pack:

```bash
python -m llm_wiki_forge integrations install-hermes \
  --hermes-root /home/tedhsu/.hermes \
  --dry-run

python -m llm_wiki_forge integrations install-hermes \
  --hermes-root /home/tedhsu/.hermes
```

Use `--no-hook` when you only want tool, skill, and test files:

```bash
python -m llm_wiki_forge integrations install-hermes \
  --hermes-root /home/tedhsu/.hermes \
  --no-hook
```

After installation, Hermes should expose stable tool names:

```text
llm_wiki_query
llm_wiki_source_search
llm_wiki_forge_sync
llm_wiki_forge_repo_add
```

The query tools are intentionally thin. They keep the Hermes registry contract but delegate query behavior to Forge.

## Query Flow

The intended evidence workflow is:

```text
llm_wiki_query
  -> routing and direct evidence
  -> llm_wiki_source_search when next_action says run_source_search
  -> read source files named by evidence
  -> answer from traceable code lines
```

Do not answer code behavior from memory. A valid answer should be grounded in an evidence pack, direct source snippets, or raw source files read after the query.

## Included Skills

| Skill | Purpose |
| --- | --- |
| `llm-wiki-build` | Main AI entrypoint for a full build flow |
| `llm-wiki-bootstrap` | Create a new LLM Wiki root |
| `llm-wiki-module-onboarding` | Build one repo into a wiki module |
| `llm-wiki-integrity-validate` | Read-only health check |
| `llm-wiki-repo-infra-backfill` | Improve one existing repo's wiki artifacts |
| `llm-wiki-master-sync` | Update wiki state from repo git changes |
| `llm-wiki-pipeline-hardening` | Promote repo fixes into reusable pipeline rules |

Copy skills from `skills/` into the target agent's skill directory when they are used outside a packaged integration.

## Expected Wiki Artifacts

After a successful build or refresh, the wiki root should contain:

```text
wiki.scope.json
Wiki/_data/modules/<repo>.json
Wiki/01_Modules/<RepoName>/<RepoName>.md
Wiki/_data/symbols/*.json
Wiki/_data/communities/*.json
Wiki/_data/query_runs/*.json
Wiki/_meta/repo_sync/<RepoName>.json
```

Older wiki roots may still contain `scripts/`. Forge no longer depends on wiki-root scripts just to recognize an existing wiki root. Packaged runtimes are preferred for new query adapters.

## Validation

For local development:

```bash
python -m compileall llm_wiki_forge
python -m pytest tests -q
python -m llm_wiki_forge integrations install-hermes --hermes-root /home/tedhsu/.hermes --dry-run
```

For query smoke tests:

```bash
python -m llm_wiki_forge code query \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --question "固定車資怎麼算" \
  --top 3 \
  --extract-limit 2 \
  --json

python -m llm_wiki_forge code source-search \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --pattern JobTraState \
  --limit 1 \
  --json
```

## Compatibility

The legacy command names remain available:

```text
sync
backfill
query
source-search
graph
```

New integrations should prefer:

```text
update
refresh
code query
code source-search
integrations install-hermes
```

Those names reflect the current ownership model: Forge handles correctness workflows; Hermes handles conversation and answer composition.
