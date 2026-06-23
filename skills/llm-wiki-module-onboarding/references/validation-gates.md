# Validation Gates

Use this reference when an onboarding command succeeds mechanically but the generated artifacts may still be too weak for a useful LLM Wiki.

All paths are placeholders. Use the values supplied by the user for `<wiki_root>`, `<repo_path>`, `<project_name>`, and `<python_command>`.

## Gate 1: Inputs

Required evidence:

- `<wiki_root>` exists and contains `wiki.scope.json`.
- `<wiki_root>/scripts` exists.
- `<repo_path>` exists and is readable from the executing environment.
- `<python_command> --version` succeeds.
- At least one smoke question exists or can be derived as `<project_name> 的主要責任是什麼？`
- Likely confused modules/repos are known or explicitly marked unknown.
- High-value entry files/symbols are collected when the repo has obvious controllers, services, workers, jobs, handlers, filters, repositories, or API endpoints.

If `project_name` is inferred from the path leaf, mention it before editing. If `repo_path` is missing, ask the user and stop. If `python_command` is missing, auto-detect or create a wiki `.venv` using the `llm-wiki-build` Python Auto-Detection rule.

If `wiki_root` is missing but `repo_path` exists, derive `<parent_of_repo>/<repo_name>-llm-wiki`, state the derived path, and use `llm-wiki-bootstrap` before onboarding. If the user provided a `wiki_root` that lacks `wiki.scope.json`, `Wiki/`, or `scripts/`, use `llm-wiki-bootstrap` at that path before continuing.

## Gate 2: Scope

After editing `wiki.scope.json`, inspect the new object:

- `logicalName` equals the stable module name.
- `actualRoot` equals the project source root supplied by the user.
- `targets` has one entry for a normal single-module repo.
- `targets[0].actualPath` equals the project source root.

For a single-module repo, avoid child expansion unless the user explicitly wants a monorepo-style split.

## Gate 3: Inventory

After refreshing inventory with the toolkit's Python entrypoint, verify both rendered and machine-readable outputs:

```bash
rg -n "<project_name>|<repo_path_fragment>" "<wiki_root>/Wiki/00_Scope_Inventory.md" "<wiki_root>/Wiki/_data/scope.inventory.json"
```

Do not continue if the project is absent.

## Gate 4: Module Build

After generating module artifacts, find the module by name or source path:

```bash
rg -n "<project_name>|<repo_path_fragment>" "<wiki_root>/Wiki/_data/modules" "<wiki_root>/Wiki/01_Modules"
```

Expected result:

- at least one JSON file under `Wiki/_data/modules`
- at least one Markdown page under `Wiki/01_Modules`
- source paths point to the new project
- semantic-card fields or their durable overlay/intake source are visible enough for routing
- overlay-derived responsibilities, boundaries, routing terms, entry symbols, or relationships are rendered inline when overlays exist
- generated Markdown has inline module semantics, not only a generic project summary
- generated JSON/Markdown can feed the query runtime's semantic intake, routing, and evidence-sufficiency gates

If the generated page is placed under a different namespace than expected but metadata is correct, report the actual path instead of forcing a rename.

## Gate 5: Semantic Extraction Readiness

Before treating a new module as query-ready, verify that generated metadata or durable overlay/intake source can support semantic routing:

- Responsibility summary says what the module owns in business terms.
- Boundary notes say what the module does not own.
- Business terms include user-facing vocabulary, not only class/file names.
- Misleading terms or confused modules are captured when the repo is easy to misroute.
- Entry points and route surface include exact files or symbols that should be extracted first.
- Dependencies/callers/callees are present when they can be inferred.
- Confidence/risk notes describe weak or generated-only areas.

If these fields do not exist in the generated schema yet, preserve the information in intake or overlay and report that the generator/schema needs a backfill.

Strong extraction seeds include both file and symbol:

```text
<relative source file> :: <class or method>
```

If a repo is known by business vocabulary that does not appear in code, store the mapping:

```text
business term -> code names/files/symbols
misleading term -> route elsewhere
common question -> read these files first
```

Passing this gate means a future agent should not need repeated broad searches before trying known files.

## Gate 6: Community Navigation Quality

After community build, inspect repo-related communities:

```bash
rg -n "<project_name>|<repo_path_fragment>|source|degraded|skip_reason|jquery|Sizzle|bootstrap|\\.min\\.js|node_modules|\\bbin\\b|\\bobj\\b" "<wiki_root>/Wiki/_data/communities"
```

Passing communities should help route business or system questions. Warning signs:

- top communities dominated by vendor libraries or minified files
- repeated hits for `jquery`, `Sizzle`, `bootstrap`, `.min.js`, `node_modules`, `bin`, `obj`, package caches, or generated assets
- communities with no visible relationship to the repo's actual responsibilities

If graph/community dependencies are unavailable, PASS requires explicit fallback community JSON with `source` and `degraded` markers. Silent stale reuse is FAIL.

## Gate 7: Query Smoke

Run a simple responsibility question first:

```bash
<python_command> -m llm_wiki_forge graph --wiki-root "<wiki_root>" --question "<project_name> 的主要責任是什麼？" --top 5 --extract --extract-limit 4
```

Open the newest JSON under `Wiki/_data/query_runs`. Passing evidence should include the new module name, source path, or generated module JSON. For implementation questions, passing evidence should include exact source files or symbols in `direct_evidence` or an equivalent evidence field.

Interpret the semantic gate strictly:

- `strong`: can answer from direct evidence or strong module evidence for responsibility-only questions.
- `partial`: onboarding can continue only if missing evidence is recorded and the question does not require implementation proof.
- `weak`: smoke test is not PASS; fix metadata/extraction seeds or escalate.

Also inspect route quality:

- selected modules include the intended repo/module for matching questions.
- rejected modules or trace data explain obvious non-matches when available.
- weak top-k evidence expands once to fallback, then converges.
- query-run JSON records route score, extraction plan source, fallback reason, and direct evidence when available.
- implementation questions reach exact files/symbols through symbol hints or equivalent extraction seeds.
- community hits preserve `source` / `degraded` metadata when fallback communities are involved.
- search behavior does not repeat identical search calls after blocked or zero-result warnings.

If query runtime cannot run because local dependencies are missing, report this as an environment gap. Do not mark the smoke gate PASS.

## Gate 8: Skill Handoff

Use these handoffs instead of piling every fix into onboarding:

- `llm-wiki-repo-infra-backfill`: the repo already exists in the wiki and needs a focused single-repo quality repair.
- `llm-wiki-pipeline-hardening`: onboarding exposes a shared generator/schema/runtime problem such as overlay-inline failure, stale community reuse, missing degraded fallback, planner ignoring symbol hints, or missing query evidence trace.
- `llm-wiki-master-sync`: the new quality invariant must be preserved during future source syncs.
- `llm-wiki-integrity-validate`: independent read-only validation is needed before sharing results.

## Common Failures

- Project missing from inventory: fix `wiki.scope.json` path, include flag, or target path.
- Module missing after build: inspect generator output and source path resolution.
- Query routes to unrelated modules only: improve module tags/summary and add clearer intake/overlay language before rerunning.
- Query loops on the same search: stop repeating the same path/pattern/glob tuple, read known files from extraction seeds, inspect the evidence pack, or add business-term-to-code-name mappings.
- Responsibility smoke is strong but implementation smoke is weak: onboarding may be structurally present but not query-ready for code facts; add symbol/extraction seeds or escalate to backfill/hardening.
- Sync state fails with missing baseline: initialize only after smoke tests pass.
