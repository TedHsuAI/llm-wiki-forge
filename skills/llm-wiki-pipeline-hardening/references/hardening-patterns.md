# LLM Wiki Pipeline Hardening Patterns

Use this reference to map one-repo onboarding or backfill findings into shared generator, runtime, and validation changes.

## Pattern 1: Overlay Inline

Symptom:

- Module Markdown only says an overlay exists or references it.
- Module JSON lacks overlay responsibilities, boundaries, routing terms, entry symbols, or relationships.
- Future rebuilds would keep the semantic card outside primary module artifacts.

Preferred fix:

- Locate the overlay application step.
- Merge overlay fields into generated module JSON under the local schema convention.
- Render the same fields in module Markdown so humans and agents can inspect them without opening separate overlay files.
- Preserve overlay as durable source material; do not make generated JSON the only copy.

Validation:

- Module JSON contains overlay-derived semantics.
- Module Markdown shows responsibilities, non-responsibilities, routing terms, entry symbols, and relationships inline.
- Regeneration preserves the fields.

## Pattern 2: Symbol-Hint-First Planning

Symptom:

- A repo backfill passes only after extraction planning uses symbol hints.
- Before the fix, extraction mostly selects lookup-table or generic community files.
- Routing score improves when exact entry symbols are present.

Preferred fix:

- In planner/query runtime code, promote high-confidence symbol hints ahead of community lookup artifacts when:
  - the route selected the module with meaningful score
  - semantic terms match the question
  - entry symbols are available
  - the question asks about responsibility, entry points, or implementation
- Keep community navigation as fallback/supporting context.
- Record extraction plan source in query-run JSON.

Validation:

- Smoke queries extract exact source files/symbols.
- Query-run JSON shows symbol hint or equivalent plan source.
- Scores and selected modules are explainable.

## Pattern 3: Community Fallback Without Graph Data

Symptom:

- Community builder reports missing graph communities.
- Existing community JSON is reused, stale, or impossible to trust.
- Useful symbols and module route surfaces exist but are not turned into navigation communities.

Preferred fix:

- Add a degraded fallback that builds communities from module metadata, dependencies, entry points, route surface, and symbol JSON.
- Mark fallback output explicitly, for example `source=symbol_derived` or `degraded=true`.
- Filter vendor/generated noise before writing communities.
- Keep graph-backed communities preferred when available.

Validation:

- Builder does not silently skip when fallback inputs exist.
- Output records whether it came from graph or symbol-derived fallback.
- Top communities are not dominated by `jquery`, `Sizzle`, `bootstrap`, `.min.js`, `node_modules`, `bin`, `obj`, package caches, or generated assets.

## Pattern 4: Query Evidence Trace

Symptom:

- Smoke tests pass but it is hard to explain why the module was selected.
- Routing score changed but no query-run field explains the delta.
- Rejected modules or fallback decisions are missing.

Preferred fix:

- Persist selected modules, rejected modules, route score, score contributors, extraction plan source, fallback reason, direct evidence, and convergence status in query-run JSON.
- Keep fields stable enough for helper scripts and future evals.

Validation:

- A query-run comparison can show score/plan/evidence differences before and after the change.
- Implementation questions cite exact source evidence.

## Pattern 5: Skill And Process Alignment

Symptom:

- Runtime/generator behavior changes but skills still describe the old flow.
- Future agents repeat manual fixes because the skill does not mention the new invariant.

Preferred fix:

- Update the relevant skill in this shareable package.
- Keep all examples path-placeholder based.
- Keep Python-first entrypoints and explicit environment-gap reporting.

Validation:

- The skill names the new gate or invariant.
- The skill does not introduce fixed machine paths or repo-specific assumptions.
