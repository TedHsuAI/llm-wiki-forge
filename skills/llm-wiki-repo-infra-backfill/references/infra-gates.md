# LLM Wiki Repo Infrastructure Gates

Use these gates when the backfill audit passes mechanically but the wiki still looks weak for semantic-first query work.

All paths must come from user input or the current wiki context. Use `<wiki_root>`, `<repo_path>`, `<repo_name>`, and `<python_command>` placeholders until the user provides concrete values.

## Gate 1: Scope And Provenance

Required evidence:

- `wiki.scope.json` contains the repo or source root.
- `Wiki/_data/scope.inventory.json` contains the repo or source root.
- Generated module files point to the intended source repo.
- Paths in generated metadata are portable for the user's chosen environment.

Prefer fixing path metadata at the source rather than adding runtime-only fallback behavior.

## Gate 2: Semantic Card

Passing metadata or durable overlays should answer:

- What this repo/module owns.
- What it does not own.
- Which business terms should route here.
- Which misleading terms should not route here by themselves.
- Which sibling modules/repos are commonly confused with it.
- Which upstream/downstream systems matter.
- Which entry files/symbols should be read first.
- Which example questions should select or reject this repo.

If generated schema has no home for these fields, record them in repo intake/workbench or curated overlay and report the generator/schema gap.

## Gate 3: Symbol And Extraction Seeds

Passing readiness needs at least one durable source for exact implementation hints:

- `Wiki/_data/symbols` entries tied to the repo.
- Module metadata `entry_points` or `route_surface` with exact files/symbols.
- Overlay/intake entries naming classes, methods, controllers, workers, jobs, handlers, or API endpoints.

Do not claim method-level readiness from a summary-only module card.

## Gate 4: Community Quality

Passing community navigation should surface business/system clusters. Treat these as warning signs:

- Top communities dominated by vendor libraries or minified files.
- Repeated hits for `jquery`, `Sizzle`, `bootstrap`, `.min.js`, `node_modules`, `bin`, `obj`, package caches, or generated assets.
- Communities with no visible relationship to the repo's actual responsibilities.

Fix with scope excludes, community filters, or durable overlay hints, then rebuild.

## Gate 5: Query Evidence

Passing smoke tests should show:

- The intended repo/module appears in selected modules for matching questions.
- Obvious non-matches are rejected or explained in trace data when available.
- Implementation questions produce exact source files or symbols in direct evidence.
- Weak evidence expands once to fallback and then converges.
- The final answer does not rely only on unrelated modules.

If query evidence is weak, improve semantic card, symbol seeds, or community navigation before changing answer prompts.

## Gate 6: Sync State

Passing repo maintenance state should show:

- Independent state file under `Wiki/_meta/repo_sync/<repo>.json` when the repo is git-backed.
- `repo_root` points to the intended source repo.
- Zero-diff runs exit without rebuild/eval/baseline acceptance.

Initialize or repair sync state only after metadata and query evidence gates pass.
