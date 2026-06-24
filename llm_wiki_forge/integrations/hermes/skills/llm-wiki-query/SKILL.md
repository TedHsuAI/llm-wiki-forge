---
name: llm-wiki-query
description: "Full LLM Wiki infrastructure: query TGDS/TaxiPlus/repo logic via Funnel Retrieval, graph runtime, and evidence packs; onboard new repos; run master sync; validate integrity; orchestrate semantic workflows; and look up system variable runtime values. Use for any local LLM Wiki question, maintenance task, or codebase lookup."
---

# LLM Wiki Query

## WSL/Linux Execution Rule

This skill copy lives under a Linux/WSL Hermes environment. Assume a Linux shell when executing from this location.

- Use `bash`, `test`, `ls`, `rg`, `python3`, or `/home/tedhsu/.hermes/hermes-agent/venv/bin/python` for runnable commands.
- Do not run Windows-only shell scripts from WSL/Hermes unless the user explicitly switches to a Windows/Codex execution context.
- Treat Windows-only snippets as Codex-desktop examples. In WSL, report the required Windows step instead of pretending the gate passed.
- For read-only query/eval work in Hermes, prefer `/home/tedhsu/.hermes/data/llm-wiki` and the Hermes venv Python.
- Build, sync, query, source-search, eval, and community runtime commands are provided by `llm_wiki_forge`. Do not depend on `scripts/` inside the wiki root; that directory is legacy only.
Use this skill to answer codebase questions from the local LLM Wiki with evidence.

## Preferred Hermes Tool Entry

When the `llm_wiki_query` tool is available, use it as the first entrypoint instead of hand-writing the `query_orchestrator` terminal command. It wraps the same runtime and returns stable fields: `decision`, `why`, `coverage`, `routing`, `shards`, `candidate_sources`, `direct_evidence`, `direct_evidence_count`, `searched_roots`, `searched_patterns`, `evidence_pack`, and `next_action`.

Slack and other chat platforms should use `detail="compact"` unless the user is explicitly debugging the runtime. Compact mode keeps snippets small and preserves full auditability through `evidence_pack`.

When `llm_wiki_query` returns `next_action=run_source_search`, call `llm_wiki_source_search` with one fixed-string pattern at a time. Keep the terminal commands below as diagnostics or fallback for sessions where the toolset is unavailable.

## Workspace

Default LLM Wiki root:

```text
/home/tedhsu/.hermes/data/llm-wiki
```

Canonical absolute paths:

```text
Wiki modules dir: /home/tedhsu/.hermes/data/llm-wiki/Wiki/_data/modules
Wiki query runs dir: /home/tedhsu/.hermes/data/llm-wiki/Wiki/_data/query_runs
Main TGDS source root: /home/tedhsu/DispatchRawdata/RD.TGDS
```

## Standard Query

When running inside WSL/Hermes and the terminal policy allows normal execution, run from the LLM Wiki root and use the Hermes agent venv Python. Do not run this from the project repo cwd, because `scripts/query_runtime` lives in the Wiki root.

```bash
cd "/home/tedhsu/.hermes/data/llm-wiki"
/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge code query --wiki-root . --question "<user question>" --top 5 --extract-limit 4 --json
```

The fixed decision flow is:

```text
semantic_intake -> graph_runtime -> evidence_gate -> ambiguity_gate -> source_search -> read_verify -> answer_gate
```

`query_orchestrator` is the main entrypoint for Slack and normal LLM Wiki Q&A. It must run graph runtime first and write an evidence pack, then return standardized `graph_status`, `coverage`, `candidate_sources`, `decision`, and `why` fields for the outer Hermes LLM to judge. It does not contain business-term alias tables. Use raw `graph_runtime` only as a diagnostic fallback when debugging the runtime itself.

Decision handling:

1. `answer_from_graph`: answer from graph `direct_evidence` only.
2. `answer_from_verified_search`: answer from `source_search` / `read_verify` evidence only.
3. `needs_semantic_expansion`: do not answer yet. The outer Hermes LLM must generate 2-5 search hypotheses from the question, graph evidence, missing coverage, and candidate sources, then call `source_search` one hypothesis at a time. Stop after at most 3 rounds.
4. `needs_user_clarification`: ask the concrete clarification question and stop.
5. `not_found_after_verified_search`: reply "目前找不到直接證據" with searched roots/patterns.

## Slack query-only mode (CRITICAL)

When running inside Slack Hermes query-only mode:

1. First check the available tool names in the current session. Do not assume `search_files`, `read_file`, or `terminal` exist.
2. If `terminal` is available, the Slack read-only guard allowlists this exact orchestrator shape:
   ```bash
   cd "/home/tedhsu/.hermes/data/llm-wiki" && /home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge code query --wiki-root . --question "<user question>" --top 5 --extract-limit 4 --json
   ```
3. The guard also allowlists `llm_wiki_forge code source-search` with fixed flags for deterministic grep. Do not use heredoc Python, shell arrays, arbitrary `python -m ...`, redirects, package installs, service restarts, or write commands. They are intentionally blocked in Slack.
4. Prefer the orchestrator result first. Inspect `decision`, `why`, `coverage`, `candidate_sources`, and `graph_status` before answering. Use `read_file` only for files named by `candidate_sources`, `read_verify`, or the evidence pack. Do not use `search_files` in Slack for LLM Wiki code search.
5. If the orchestrator is not immediately runnable under the allowlist, skip repeated terminal attempts and go straight to Wiki module JSON plus exact source file verification.
6. The module directory is **always** `/home/tedhsu/.hermes/data/llm-wiki/Wiki/_data/modules`. Never use `/home/tedhsu/.hermes/data/llm-wiki/_data/modules`.
7. The query-run directory is **always** `/home/tedhsu/.hermes/data/llm-wiki/Wiki/_data/query_runs`.
8. If no file/search/terminal tool is available, do not call missing tools and do not expose tool names as an error. Reply in Traditional Chinese that the current Slack session cannot access source evidence, so the answer cannot be verified here; ask for a rough file/API/table hint or suggest retrying from a full Hermes/Codex context.
9. In Slack, call `llm_wiki_query` with compact defaults. Do not request `detail="full"` unless the user is debugging evidence-pack generation.
10. Treat `reused_evidence_pack=true` according to `reuse_decision`, not by itself. Answer directly only for `direct_reuse` or `validated_reuse`. If `reuse_decision=hint_only`, use the pack only as routing evidence and run one narrow verification search before answering. If `reuse_decision=bypass`, ignore the pack for answering.
11. For `shards.query_shape=multi_module`, answer by merging the returned shard summaries first. Do not fan out broad searches unless the shard summary is insufficient and the user needs code-level depth.
12. Per Slack turn budget: at most 1 broad `llm_wiki_query`, 1 narrow follow-up `llm_wiki_query`, 3 `llm_wiki_source_search` calls, and 4 source file reads. If the answer is still partial, answer the supported part and mark the rest as "目前找不到直接證據".

Tool schema rule:

- `execute_code` accepts only `{"code": "<python code>"}`. Never call `execute_code` with `{"command": "..."}`.
- If `terminal` is unavailable and a shell command must be run through `execute_code`, wrap it in Python `subprocess.run(...)`, capture stdout/stderr, and print only the useful summary.
- If a tool returns a schema error such as `No code provided`, fix the call shape once. Do not repeat the malformed call.

Outer semantic iteration:

When `decision=needs_semantic_expansion`, the runtime has intentionally stopped before guessing. The outer Hermes LLM should generate hypotheses at that moment from the user question plus the returned evidence/state. Each hypothesis must include the semantic assumption, why it follows from current evidence, fixed-string patterns, optional roots, and a stop condition. Do not read a prewritten business alias table, and do not add mappings in this skill for specific Chinese business phrases.

Run only one hypothesis at a time:

```bash
cd "/home/tedhsu/.hermes/data/llm-wiki" && /home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge code source-search --wiki-root . --pattern "<LLM-generated fixed string>" --limit 20 --json
```

After each `source_search`, judge the returned matches/read-verify snippets as evidence. If several hypotheses remain plausible but none has fact-grade support, ask the user to choose a direction instead of continuing blind search.

Source-search limit policy:

- First pass uses `--limit 20`.
- If `total_count=20` and `truncated=true`, do not immediately expand. First refine the pattern, add a narrower `--root`, or read the strongest returned files.
- Expand to `--limit 80` only when the first 20 matches are relevant but clearly incomplete.
- For broad/common terms such as `Rank`, `RankId`, `JobInfo`, `SpecOrdObj`, `即時`, table names reused across many files, or generic status words, keep `--limit 20` and narrow the scope before any expansion.

Hard convergence limit:

- Run at most three semantic/source-search hypotheses for one user question.
- Stop earlier if two consecutive searches produce no new source paths or no new fact-grade snippets.
- Do not send Slack messages that narrate "trying different keywords", "searching again", or tool-switching. Continue internally, then answer with conclusion, evidence, and missing evidence.
- If the strongest evidence answers only part of the question, answer that part and mark the rest as "目前找不到直接證據" instead of spending the full iteration budget.
- Do not expand compact tool payloads into raw evidence unless the user asks for debug detail. Use `evidence_pack` as the audit pointer.

Large-query shard policy:

- `llm_wiki_query` may return up to three deterministic shard summaries for broad multi-module questions. Use these summaries as the parent merge layer: deduplicate file paths/symbols, answer from the strongest direct evidence, and list only the meaningful modules.
- Do not run the same broad question separately for each module unless the user explicitly asks for exhaustive research. For normal Slack Q&A, run narrow follow-up checks only for the missing shard.

Cache reuse safety:

- `freshness_status=fresh` means the source repo versions match the cached pack.
- `freshness_status=version_changed_checked_ok` means Git changed but the evidence file or snippet still validated.
- `freshness_status=legacy_unknown` means the old pack did not record source versions. Use it directly only when `reuse_decision=validated_reuse`; otherwise treat it as a hint.
- `freshness_status=stale_logic_changed` or `version_changed_needs_check` means do not answer from the cached pack.
- Questions containing freshness terms such as latest/current/master/更新後 should bypass direct cache reuse and verify source.

Subagent policy:

- Subagents are V2 fallback only. Use `delegate_task` only when the query is broad multi-module, routing confidence is weak, and deterministic shard summaries are insufficient.
- Subagent tasks must be leaf tasks, read-only, and scoped to one shard/module. Use only the LLM Wiki/read-only toolsets available in the session; do not allow subagents to edit files, restart services, install packages, or delegate again.
- Parent context must receive only structured summaries: `decision`, `evidence_refs`, `files`, `confidence`, and `open_questions`. Do not ask subagents to return raw transcripts or full evidence packs.

Evidence gate / exact identifier rule:

If the user asks about an exact code-looking identifier such as `JobTraState`, `Mixpanel`, `TaxiPlusQuotation`, a DTO property, enum, class, method, API name, SP/function name, or PascalCase/camelCase token, graph-runtime evidence is not sufficient unless that exact identifier appears in one of:

- `synthesis_inputs.direct_evidence[].code`
- `synthesis_inputs.direct_evidence[].symbol`
- `synthesis_inputs.direct_evidence[].file_path`
- a raw source `grep`/`rg` result

If the exact identifier is absent, ignore `semantic.evidence_sufficiency.status=strong` for that question and immediately run deterministic source search. In Slack, prefer:

```bash
cd "/home/tedhsu/.hermes/data/llm-wiki" && /home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge code source-search --wiki-root . --pattern "EXACT_IDENTIFIER" --limit 20 --json
```

Only answer "找不到" after this exact identifier search and the canonical fixed-root matrix both produce no direct source evidence.

SQL / database answer gate:

When the user asks for SQL, table names, columns, DB status values, or "怎麼查", do not synthesize a full SQL statement from C# object names alone. Before giving runnable SQL, `source_evidence` must prove all of these:

1. The real DB object: table/view/SP result set, not only a C# class, DTO, in-memory object, enum, or variable name.
2. The exact join key or lookup path between the requested entities.
3. The exact column used for each predicate.
4. The stored value domain, including bit flags, enum shifts, casts, or client-value-to-DB-value transforms.
5. The status-domain meaning. For example, do not treat `IVE_Info.Status`, `IVE_Status.ExecJob`, `IVE_Status.IsOnline`, and an in-memory `mIVE.Status` as interchangeable unless direct evidence proves the mapping.

If any item is missing, answer with only the proven pieces and a clear "目前還不能直接給完整 SQL，缺 X 的直接證據". A skeleton SQL is allowed only if every unverified table/column/predicate is visibly marked as a placeholder such as `<待確認表名>`; never present placeholders as final SQL.

Hard SQL pitfall:

- Do not use a C# object/class name as a SQL table name unless source evidence shows it in SQL (`FROM`, `JOIN`, `CREATE TABLE`, table script, repository SQL, or SP output contract).
- Do not copy enum raw values into SQL predicates when source evidence shows the value is transformed before storage.
- If source evidence only shows a stored procedure call but not the SP body or result schema, say that the SQL cannot be verified from the currently read evidence.
- If several status concepts are plausible, ask for scope or state the ambiguity instead of choosing one by intuition.

Ambiguity gate:

When the orchestrator returns `answer_gate.status=needs_user_clarification`, ask the included clarification question exactly in normal Traditional Chinese. Do not keep searching, do not expose internal terms, and do not choose one candidate by intuition. This is expected for terms like `營業狀態` when IVE status, driver/vehicle business status, and dispatch task status are all plausible but none is fact-grade evidence yet. If the user already gave a scope hint such as `CoreServers`, continue in that scope and do not ask again.

**Fallback if query_orchestrator is unavailable** (e.g., WSL environment without Python, missing query_runtime scripts):
1. Search relevant module JSON files under `Wiki/_data/modules/*.json` for business tags (e.g., `estimated-fare`, `dispatch`).
2. Use `source_search` to locate key source files (e.g., `TaxiFareCalc.cs`, `CostEstimatesUtil.cs`). In Slack, do not fall back to `search_files`; if the fixed commands and source reads are unavailable, answer that direct evidence cannot be verified in the current session.
3. Read the identified source files directly with `read_file` to extract the logic.
4. Base the answer on the source code evidence, mentioning file paths and method/class names.
5. If source search/read tools are not available or are blocked with no new evidence, summarize as "目前找不到直接證據" and list the checked keywords/known search scope. Do not expose internal tool names, guardrail terms, or missing-tool errors to the Slack user.

**Fallback if Wiki has no business logic details**: when Wiki module pages only contain structural info (projects, solutions) but no business logic, see `references/wiki-fallback-to-source.md` for the technique of deriving source paths from module JSON and searching raw source code directly.

## source_search fallback (CRITICAL)

`source_search` is the deterministic wrapper for repo-wide raw source verification. It uses fixed-string grep by default and expects explicit `--pattern` values from the outer LLM or exact-identifier gate. It does not do semantic expansion and does not own business aliases. Do not hand-build shell pipelines such as `a|b|c`.

```bash
cd "/home/tedhsu/.hermes/data/llm-wiki" && /home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge code source-search --wiki-root . --pattern "SYS_Variables" --limit 20 --json
```

`search_files` is not part of the Slack LLM Wiki search path. Treat any empty or blocked `search_files` result as an internal signal only, not user-facing evidence.

**應對策略**：
1. 改跑 `query_orchestrator` 或 `source_search`，不要重複同一組 `search_files`。
2. 若固定 runtime/source_search 和必要 source read 都不可用，直接回答「目前找不到直接證據」並列出已查過的專案和關鍵字。
3. 不要對 Slack 使用者描述工具零命中、索引推測、或任何工具切換過程。只輸出 evidence 結論、缺口、或具體澄清問題。

## System Variable Runtime Value Lookup

When source evidence finds a system parameter lookup such as `SYS_Variables`, `SystemVariable`, `GetVarValueBy`, `VarGroup`, or `VarKey`, the source code may only prove which parameter is read, not the current runtime value.

If both `VarGroup` and `VarKey` are present in source evidence, use `tgds-system-variable-setting` to query the stage API:

```bash
/home/tedhsu/.hermes/hermes-agent/venv/bin/python /home/tedhsu/.hermes/skills/tgds-system-variable-setting/scripts/get_system_variable_setting.py --var-group "<VarGroup>" --var-key "<VarKey>" --json
```

Rules:

1. Do not guess missing `VarGroup` or `VarKey`.
2. Treat the API result as runtime configuration evidence and the source file as code evidence.
3. In the answer, cite where `VarGroup` / `VarKey` came from and then report `VarValue`, `VarText`, and `Comment` from the API response.
4. If the API cannot be reached or returns empty/error, say the runtime value could not be verified from the stage API.

## Canonical Search Contract

This skill owns code search rules for LLM Wiki answers. Other helpers may route to this skill, but they must not duplicate or override this search boundary.

When the question is about dispatch, car search, booking, fare, assignment, cancellation, or TGDS business rules, `TGDS.WebAPI`, `TGDS-Dispatch-WebAPI`, `DispatchRule`, and `CoreServers` are related by default. Do not treat one empty module result as proof that the behavior does not exist.

If graph runtime returns weak, irrelevant, empty, or single-module evidence, verify against this fixed matrix before answering negatively:

```text
/home/tedhsu/DispatchRawdata/RD.TGDS/DEV/TGDS-TaxiPlus/01_Code/TGDS.WebAPI
/home/tedhsu/DispatchRawdata/TGDS-Dispatch-WebAPI
/home/tedhsu/DispatchRawdata/DispatchRule
/home/tedhsu/DispatchRawdata/RD.TGDS/DEV/TGDS/CoreServers
```

Required behavior:

1. Use `query_orchestrator` first; graph runtime is the core source of routing/evidence, while the orchestrator standardizes state for the outer Hermes LLM.
2. If `decision=needs_semantic_expansion`, generate the next keyword/root hypothesis from the returned evidence and missing coverage at runtime. Do not rely on a hardcoded Chinese-business-term mapping table.
3. If multiple plausible routes or hypotheses exist but no direct evidence proves the requested fact, ask the user to choose a direction instead of guessing or continuing blind search.
4. For any negative answer, briefly state the projects and representative keywords searched.

## Fast path for 預估車資 / 固定車資 / 計算公式

These questions should not spend multiple rounds bouncing between modules.

Do not start these questions with broad `search_files`. First run `query_orchestrator` or inspect the newest matching evidence pack under `/home/tedhsu/.hermes/data/llm-wiki/Wiki/_data/query_runs` (for example filenames containing `固定車資`, `taxiplusv2`, or `計算公式`). If it contains relevant `synthesis_inputs.direct_evidence`, answer from that or read the named source files. If no evidence pack exists, read the exact files below first, then use targeted `source_search` only if the answer is still missing.

Do not call `search_files` with pipe-combined patterns such as `固定車資|FixedFare|FixedPrice` or `預約池|ReservationPool|Reservation.*Pool` as a first strategy. In Slack/Hermes this can behave like a literal pattern and create false zero-result loops. Use one simple keyword at a time (`固定車資`, then `IsFixedPrice`, then `TaxiPlusQuotation`) through `source_search`.

Read these exact files first:

```text
/home/tedhsu/DispatchRawdata/RD.TGDS/DEV/TGDS-TaxiPlus/01_Code/TGDS.WebAPI/Services/TaxiFareCalc.cs
/home/tedhsu/DispatchRawdata/RD.TGDS/DEV/TGDS-TaxiPlus/01_Code/TGDS.WebAPI/Controllers/APP/EstimatedFare/Taxi.cs
/home/tedhsu/DispatchRawdata/RD.TGDS/DEV/TGDS-TaxiPlus/01_Code/TGDS.WebAPI/Controllers/APP/Quotation/Quotation_Make.cs
/home/tedhsu/DispatchRawdata/RD.TGDS/DEV/TGDS-TaxiPlus/01_Code/TGDS.WebAPI/Models/App/Quotation.cs
/home/tedhsu/DispatchRawdata/RD.TGDS/DEV/TGDS-TaxiPlus/01_Code/TGDS.WebAPI/Services/TaxiPlusV2Service.cs
```

Primary symbols:

- `TaxiFareCalc.TaxiPlusQuotation`
- `TaxiFareCalc.TaxiPlusQuotationComputeFare`
- `TaxiFareCalc.InceptPrice`
- `TaxiFareCalc.EndPrice`
- `Quotation.DoEstimated`
- `TaxiPlusV2Service.CalculateSingleCardQuotationInternal`

Routing rule:

1. Treat the fare formula itself as a `TGDS.WebAPI` question first.
2. Only read `DispatchRule/.../FixedFareDiversifiedReguFilter.cs` after the formula files above, and only for dispatch applicability or driver-group regulation.
3. Do not spend repeated search rounds in `DispatchRule` when the user asked for the fare formula; the formula lives in `TGDS.WebAPI`.

## Query Convergence Rules

This skill should broaden search coverage, not loop forever.

1. Stop repeating a `search_files`, `grep`, graph-runtime, or orchestrator query when it produces no new evidence.
2. If `search_files` returns `BLOCKED`, do not call `search_files` again with the same `path` + `pattern` + `file_glob` + `output_mode`. Switch to `read_file` on known candidate files, inspect the newest query-run evidence pack, run `query_orchestrator` once, or change to a genuinely different root and simpler keyword.
3. If the attempted pattern contains `|` and returns zero results, do not repeat it. Split it into simple keyword searches or switch to direct source/evidence-pack reading.
4. If a search path has produced no new evidence twice, change strategy once: read the strongest candidate files already found, inspect the evidence pack, or broaden to the fixed four-root matrix.
5. After the fixed four-root matrix and one broader keyword pass, synthesize an answer from the strongest evidence already collected. State the missing piece plainly instead of launching another equivalent search.
6. If partial evidence answers the user's main question, answer with that partial result and mark the uncertain part. Do not use the full iteration budget chasing a perfect SP/function name.
7. If the missing part is essential and still not found, ask the user for a rough project/file/SP hint rather than continuing automated search.
8. Never expose internal loop-control wording, guardrail states, retry narration, zero-match diagnostics, or indexing hypotheses to the user. Translate them into a normal answer: "目前找不到直接證據；我已查過 X/Y/Z，建議下一步查 A 或請提供 B。"

Deterministic source-search pattern:

```bash
cd "/home/tedhsu/.hermes/data/llm-wiki" && /home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge code source-search --wiki-root . --pattern "KEYWORD" --limit 20 --json
```

Use this for normal questions such as:

- `目前搜車中加小費，加小費的 API 詳細資訊`
- `taxiplusv2 固定車資的計算方式`
- `Quotation Make 使用的固定車資計算方式`
- `taxiplusv2 固定車資路線圖的畫圖邏輯，以及 google routes 轉 direction 的邏輯`

## Evidence Pack Reading (CRITICAL — read this first)

The evidence pack JSON has a nested structure. Always inspect top-level keys first before accessing nested fields:

```
Top-level keys:
  - routing.selected_modules      ← modules matched by the graph router
  - semantic.intake               ← question type, must-answer checklist, and guardrails
  - semantic.routing              ← route ambiguity and fixed-matrix recommendation
  - semantic.evidence_sufficiency ← answer-readiness gate and next step
  - navigation.extraction_plan    ← files to read, with intent scores
  - synthesis_inputs.direct_evidence  ← code snippets already extracted
  - challenge.findings            ← warnings from the extraction pass
  - symbol_hints                  ← symbol-level hints
  - trace                         ← query execution trace
```

**Common mistake**: accessing `data['selected_modules']` directly instead of `data['routing']['selected_modules']`. This returns `KeyError` or empty results.

**Evidence pack already contains code**: `synthesis_inputs.direct_evidence` is a list of objects, each with:
- `file_path` — absolute path to the source file
- `symbol` — method or class name (e.g., `TaxiFareCalc.TaxiPlusQuotation`)
- `code` — the full extracted code snippet
- `start_line` / `end_line` — line range

**Priority**: when `direct_evidence` contains relevant code, use it directly. If `direct_evidence` does NOT contain the specific symbol/parameter the user asked about, **read the raw source files listed in `direct_evidence` or `extraction_plan` directly** before falling back to external grep/search. The extraction plan already identified candidate files — read them first to confirm whether the symbol exists in the codebase. Only use external grep when the files identified by the Wiki are irrelevant or the symbol is not found after reading them.

**Verification step**: after loading the evidence pack JSON, always print or inspect the top-level keys first:
```python
import json
with open(evidence_pack_path) as f:
    data = json.load(f)
print(list(data.keys()))  # verify structure before accessing nested fields
```

## Semantic Evidence Gate (CRITICAL)

Always read the semantic fields before writing the answer:

```python
semantic = data.get("semantic", {})
intake = semantic.get("intake", {})
routing = semantic.get("routing", {})
sufficiency = semantic.get("evidence_sufficiency", {})
print(intake.get("question_type"), routing.get("ambiguity"), sufficiency.get("status"), sufficiency.get("next_step"))
```

Use the gate this way:
1. `semantic.intake.must_answer` is the checklist for the final answer.
2. `semantic.intake.not_asking` prevents plausible but wrong neighboring answers, such as answering a fare formula question from DispatchRule-only applicability evidence.
3. `semantic.routing.ambiguity=medium/high` means the top module is provisional; read planned files or broaden before answering.
4. `semantic.routing.needs_fixed_matrix=true` means a negative answer must verify the canonical four roots first.
5. `semantic.evidence_sufficiency.status=strong` means answer from `direct_evidence`.
6. `status=partial` means read planned source files or answer only the directly proven part with uncertainty.
7. `status=weak` means do not synthesize a confident answer; escalate to fixed-matrix verification, `llm-wiki-repo-infra-backfill`, or `llm-wiki-pipeline-hardening`.

**PITFALL — semantic fields are often empty**: In many evidence packs, `semantic.intake`, `semantic.routing`, and `semantic.evidence_sufficiency` are empty `{}` even when `direct_evidence` contains valid code snippets. Do NOT treat empty semantic fields as "no evidence" — always check `synthesis_inputs.direct_evidence` regardless. If semantic fields are empty but direct_evidence has content, proceed with direct_evidence. If semantic fields are empty AND direct_evidence is empty or irrelevant, escalate to fixed-matrix verification.
7. `status=weak` means do not synthesize a confident answer; escalate to fixed-matrix verification, `llm-wiki-repo-infra-backfill`, or `llm-wiki-pipeline-hardening`.

When this gate is not enough for a broad or ambiguous question, use `llm-wiki-query-semantic-workflow` to decide whether to run a focused source-inspection agent or escalate to wiki infrastructure work.

## Evidence Ledger and No-Guess Rule (CRITICAL)

Before answering any TGDS/TaxiPlus business-rule question, build a small evidence ledger in your head:

1. `source_evidence`: direct source file reads with line numbers, evidence pack `synthesis_inputs.direct_evidence`, module JSON fields, or valid helper references with evidence paths.
2. `orientation_only`: context compaction summaries, prior assistant turns, Slack thread context, memories, reasoning notes, and previous conclusions.
3. `unsupported`: any claim not present in `source_evidence`.

Answer only from `source_evidence`. Never promote `orientation_only` into a factual answer.

Hard stop rules:

1. If a claim names a member/customer segment, business code, special-case exception, numeric limit, scheduler interval, or one-off branch, it must appear in `source_evidence`.
2. If the evidence only proves a general rule, do not add a named exception or product-specific caveat.
3. If a search for a named exception is empty after the cross-project search contract, answer "目前找不到直接證據" and list searched roots/keywords.
4. If the user asks "證據在哪裡" and the previous answer has no direct artifact, retract the unsupported claim. Do not replace it with another guess.
5. If a context-compaction summary says something was already found, re-read the named file or evidence pack before citing it.

## Slack Helper Cache Handling

Hermes may preload `xxxxx-slack-helper` skills that contain cached answers under `references/*.md`.

1. Only treat helpers named `*-slack-helper` as Slack cache helpers.
2. Before using a cached reference, read its frontmatter. It must contain `status: valid` or `status: stale`.
3. If `status: valid`, the cached answer can be used as a fast path, but mention or retain its evidence paths when answering code/business-rule questions.
4. If `status: stale`, do not answer from that cached content. Run the normal `llm-wiki-query` graph runtime or one focused source verification pass.
5. After re-verification, update the cached reference only when the refreshed evidence is strong enough:
   - set `status: valid`
   - set `last_verified` to today's date
   - keep `affected_modules` aligned to canonical module names such as `DispatchRule`, `TGDS.WebAPI`, `TDC`
   - replace stale body content with the refreshed conclusion and evidence
6. If verification is weak or incomplete, leave `status: stale` and answer with the uncertainty instead of refreshing the cache.
7. When creating a new Slack helper cache, create `xxxxx-slack-helper/SKILL.md` with `cached: true`, `affected_modules`, and `last_verified`; put cached answer bodies in `references/*.md`, not in the main instructions.
8. If a similar cached reference already exists, update that reference instead of creating a duplicate boundary for the same question.
9. Do not implement stale marking here. Query only consumes `valid`/`stale` and refreshes content after evidence; master-sync owns source-change invalidation.

## PM-Facing Explanation Style (CRITICAL)

When the user asks for an explanation meant for PMs or non-technical stakeholders:
- **Never** mention internal code names like `TaxiPlusV2`, class names, method names, or file paths in the main explanation.
- Use **business terms** only: 「預約價格」、「起跳價」、「里程費」、「時間費」、「倍率」等。
- If the user says something like "pm 不會知道 X 這種東西，在講簡單一點", immediately simplify: remove all engineering jargon, use plain business language, and give concrete examples.
- Structure: concept → steps → example → edge cases. No code snippets in the main body.
- Code references belong only in the evidence section at the very end.

## Answering Rules

1. Do not answer from memory when the question is about TGDS/TaxiPlus code behavior.
2. Do not answer from context compaction summaries, prior assistant turns, Slack thread snippets, or reasoning notes. Use them only to choose what to verify.
3. Run the query runtime, then open the generated evidence pack under:

```text
Wiki/_data/query_runs/
```

4. Base the answer on:
   - selected modules
   - community hits
   - extraction plan
   - direct evidence code snippets
   - challenge findings
5. If a named exception, member/customer code, numeric limit, or one-off branch is not present in direct evidence, mark it as unsupported and omit it from the conclusion.
6. If the runtime returns weak, irrelevant, or missing evidence, say so clearly and recommend a Wiki hardening task instead of fabricating.
7. Mention key file paths and method/class names in the final answer.
8. When encountering unexpected results from evidence pack reading, verify the actual structure first before assuming external issues (permissions, missing data, etc.). The most common cause is incorrect key path.

## Health Check

When changing Wiki metadata, router/planner logic, gold cases, or query behavior, run both:

```bash
/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge eval --wiki-root . --runtime graph
/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge eval --wiki-root . --runtime classic
```

Current expected pattern:

- Graph runtime should pass all graph cases.
- Classic runtime may skip graph-only cases.

## Master Diff Update

When the user says the source repo has moved to a newer master/head and Wiki must be updated, use:

In WSL/Linux for diff planning or per-repo sync state only:

```bash
/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge update \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key "<repoKey>" \
  --dry-run
```

To accept a per-repo baseline in WSL/Linux only after validation passes and the user asked for it:

```bash
/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge update \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --source-root /home/tedhsu/DispatchRawdata \
  --repo-key "<repoKey>"
```

Review the generated plan under:

```text
Wiki/_meta/master_sync_runs/
```

Do not accept a baseline just because a diff plan was generated. The Forge `update` command accepts the baseline by default only after its update gates pass; use `--dry-run` first when the user did not explicitly ask to update.

## Community File Path Mismatch (WSL vs Windows)

When extraction fails with `Refusing to read path outside wiki.scope.json whitelist: /mnt/d/...`, see `references/community-path-mismatch.md` for diagnosis and fixes. This happens when graphify (Windows) produces community files with Windows paths, but wiki.scope.json only has WSL paths in the whitelist.

## Fallback to Source Code (when Wiki has no business logic)

When Wiki module pages only contain structural info but no business logic:

1. Read `references/wiki-fallback-to-source.md` for the technique of deriving source paths from module JSON.
2. Identify the entry point from evidence (e.g., `Quotation_Make.cs`, `EstimatedFareController.Taxi`).
3. Trace the call chain: entry → helper → service → parsing logic.
4. Search raw source code for key classes/methods (e.g., `GenAddressObj`, `AddrSplit`).
5. Read the identified source files directly to extract the actual logic.

### Example: English Address Parsing Flow (2026-05-07 session)

When Wiki evidence was insufficient for "預估車資牌卡 輸入英文地址 會怎樣":

1. Wiki returned `Quotation_Make.cs` and `MethodHelper.cs` as evidence but no English-address specifics.
2. Traced: `QuotationController.Make()` → `MethodHelper.GenAddressObj()` → `AddressSpilt.AddrSplit()`.
3. Found `AddrSplit` uses Chinese-only regex patterns (`[縣市]`, `[區]`, `[路街道]`).
4. English addresses fail parsing → `City` is blank → fallback defaults to `台北市`.
5. Key insight: `GetAddrCity()` has a GIS polygon fallback, but quotation flow may not use it.

This pattern is useful for any question about address parsing, geocoding, or locale handling.

## Source Path Provenance (when asked "where does the path come from?")

When the user asks where the source code path in evidence comes from, see `references/source-path-provenance.md` for the five-layer trace:

```
wiki.scope.json (manual whitelist, ROOT SOURCE)
    ↓ read
scope.inventory.json (auto-generated)
    ↓ read + transform
llm_wiki_forge build/backfill (writes source_paths)
    ↓ write
modules/<module>.json (source_paths field)
    ↓ read at query time
graph_runtime → direct_evidence (file_path)
```

To change a source path, edit `wiki.scope.json` → `actualPath`, then re-run `llm_wiki_forge build` or `llm_wiki_forge backfill`.

## Common Follow-up

If a query fails because the Wiki lacks domain vocabulary, update one or more of:

- `llm_wiki_forge/resources/scripts/query_runtime/router.py`
- `llm_wiki_forge/resources/scripts/query_runtime/planner.py`
- `Wiki/_eval/query_gold_set.json`
- `Wiki/_data/modules/*.json`
- `Wiki/_data/communities/*.json`
- `Wiki/_data/symbols/*.json`

Then rerun graph/classic eval.

---

# LLM Wiki Infrastructure — Subsections

The following subsections cover the full LLM Wiki lifecycle: onboarding, sync, integrity validation, semantic workflow orchestration, and system variable lookup. Each subsection is self-contained but cross-references the others.

## Subsection: Module Onboarding

Use when a repo should be explicitly added to an LLM Wiki. The implementation entrypoint is `llm-wiki-forge`; do not edit `wiki.scope.json` by hand unless repairing a failed Forge run.

No source or wiki path is canonical. Use the paths provided by the user or the active Hermes environment for this run.

### Required Inputs

- `repo`: source repo path provided by the user
- `source_root`: parent/root that the repo must stay under
- `wiki_root`: LLM Wiki root provided by the user
- `python`: current Hermes/Forge Python or user-provided interpreter
- `repo_key`: stable registry key; default to repo folder name
- `wiki_path`: target module logical name; default to `repo_key`
- `tracked_branch`: default to the repo's current branch
- `schedule`: optional cron expression
- at least one smoke question when the user has a known query scenario

### Primary Command

```bash
<python> -m llm_wiki_forge repo add \
  --repo "<repo>" \
  --wiki-root "<wiki_root>" \
  --source-root "<source_root>" \
  --repo-key "<repoKey>" \
  --wiki-path "<wikiPath>"
```

Add `--schedule "<cron>"` only when the repo should also be registered for future scheduled sync. Add `--no-build` only for a registry-only repair.

### What Forge Must Do

- validate repo path stays under the provided `source_root`
- update exactly one repo entry in `wiki.scope.json`
- update exactly one repo entry in `Wiki/_meta/repo_sync/repos.json`
- run scope/module/community/query validation unless `--no-build` is supplied
- initialize `Wiki/_meta/repo_sync/<repoKey>.json` for git-backed repos
- leave query runtime under `scripts/query_runtime` untouched during phase one

### Validation Gates

Onboarding is complete only when:

- scope inventory includes the repo and excludes `.git`, `.vs`, `bin`, `obj`, `node_modules`, packages, and test output
- module JSON and Markdown exist for the repo
- generated metadata describes this repo, not a neighboring TGDS/Dispatch module
- important entry files/symbols are discoverable or a generator gap is reported
- community navigation is fresh or explicitly degraded
- smoke query evidence selects the intended module for responsibility questions
- implementation questions have direct source evidence before claiming a code fact
- per-repo sync state exists when the source is git-backed

### Failure Rules

- Stop after a failed Forge command; inspect stdout/stderr and report the failed gate.
- Do not substitute local-machine default paths for missing user inputs.
- Do not hand-edit generated JSON/Markdown as the only durable fix.
- Do not initialize or accept baseline before smoke evidence is acceptable unless the user explicitly accepts the risk.

## Subsection: Master Sync

Use for durable LLM Wiki maintenance from source git changes. Build/sync/onboarding execution is owned by `llm-wiki-forge`; do not call wiki-root maintenance scripts as the primary path.

### Primary Scheduled Command

For a registered repo, run:

```bash
<python> -m llm_wiki_forge update \
  --wiki-root "<wiki_root>" \
  --source-root "<source_root>" \
  --repo-key "<repoKey>"
```

Use `--dry-run` for diagnostics and `--skip-fetch` only when intentionally avoiding network/git remote checks.

### Result Semantics

- `NO_CHANGE`: reply exactly `[SILENT]` for scheduled local deliveries.
- `UPDATED`: report `repo_key`, `tracked_branch`, `before_commit`, `after_commit`, `graphify_cleanup_removed_count`, `full_sync_report_markdown`, `diff_report_markdown`, `full_sync_status`, and `accepted_baseline`.
- `DRY_RUN`: report it as a dry run and include `before_commit`, `remote_commit`, and `sync_reason`.
- `BLOCKED`, `FETCH_FAILED`, `DIVERGED`, `UPDATE_FAILED`, `SYNC_FAILED`: summarize the failure and include any report paths present.

### Timeout Handling (CRITICAL — exit code 124)

When the command exits with code 124 (timeout) and produces **no stdout / no result_status**:

1. **Do NOT treat this as `NO_CHANGE` or `[SILENT]`** — the command did not complete.
2. Report the timeout explicitly: exit code 124, no result_status produced, no new files in `Wiki/_meta/master_sync_runs/`.
3. Check `master_sync_state.json` or `repo_sync/<repoKey>.json` to confirm no baseline was accepted.
4. Note the latest diff snapshot (e.g., `diff_YYYYMMDD_HHMMSS`) and whether it includes binary files (`.dll`, `.pdb`, `.XML` in `bin/Release/`). Binaries should be excluded from sync scope.
5. Recommend re-running with a longer timeout (600s–900s minimum) or splitting into `--dry-run` first, then accept separately.
6. Do not narrate internal retry logic to the user; just state the timeout and the recommended next step.

**Recurring pattern**: Since June 11, 2026, this timeout has occurred 10+ times across multiple sessions. The root cause is the accumulated commit history gap (baseline from 2026-05-07 vs. HEAD in 2026-06-22 = ~46 days) combined with WSL-mounted source root performance. A full sync with 21 changed files completed in ~6m9s; the `rebuild-modules-graphify` step alone took ~6 minutes. A 300s timeout is insufficient for any non-trivial sync.

**Mitigation checklist**:
- Increase cron timeout to 600s–900s (minimum 7 minutes) for both `RD.TGDS` and `DispatchRule` repos.
- Run `--dry-run` first to validate the diff plan before `--accept-baseline`.
- Accept the baseline more frequently (e.g., weekly) to keep the gap small.
- Exclude `bin/Release/` and other build artifacts from sync scope to reduce file count.

### Validation Gates

- the repo is on its configured branch and has no blocking dirty changes
- fetch/ff-only update succeeds or there is no remote change
- changed files exist; zero-diff runs do not accept baseline
- Forge full sync completes module rebuild, community rebuild, overlay/eval gates where available
- the per-repo state file points to the intended repo root

If eval or query dependencies are unavailable, report the gap clearly. Do not call that a clean pass unless the user explicitly accepts the residual risk.

### Quality Checks

For impacted repos or runtime changes, inspect:

```bash
rg -n "<repo_or_module>|owns|not_owns|business_terms|misleading_terms|entry_symbols|routing_examples" \
  /home/tedhsu/.hermes/data/llm-wiki/Wiki/_data/modules \
  /home/tedhsu/.hermes/data/llm-wiki/Wiki/01_Modules

/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge code query \
  --wiki-root /home/tedhsu/.hermes/data/llm-wiki \
  --question "<repo_name> 的主要責任是什麼？" \
  --top 5 --extract-limit 4 --json
```

### Safety Rules

- Do not run destructive git commands such as reset, checkout, or clean.
- Do not accept baseline on zero-diff runs.
- Do not bypass Forge with local maintenance scripts unless explicitly doing a legacy fallback diagnosis.
- Do not delete wiki-root `scripts/` until cron, skills, tools, and Forge no longer reference the remaining runtime pieces.

## Subsection: Integrity Validate

Use as the independent safety gate for an existing LLM Wiki. It validates that the wiki can still route, navigate, extract, and answer from evidence after another workflow runs.

### Safety Contract

This skill is read-only by default.

Do not:

- edit `wiki.scope.json`
- accept a sync baseline unless the user explicitly asked for baseline acceptance
- run legacy `Sync_Master_*` scripts from the wiki root
- hand-edit generated module/community/query JSON
- delete stale files
- start backfill/hardening repairs

If validation finds a problem, report the failure and route the fix to the correct subsection.

### Modes

- `quick`: checking whether the wiki is broadly safe after a small change.
- `focused`: validating one repo after onboarding/backfill/hardening.
- `full`: validating shared generator/runtime/master-sync changes.

### Validation Flow

#### 1. Static Structure Check

From `wiki_root`, verify required files and directories exist:

```bash
test -f ./wiki.scope.json
/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge --version
test -d ./Wiki/_data/modules
test -d ./Wiki/01_Modules
test -d ./Wiki/_data/query_runs
```

For focused mode, verify the target module appears in:

```bash
rg -n "<module_or_repo>|<source_path_fragment>" ./Wiki/_data/modules ./Wiki/01_Modules
```

#### 2. Generated Artifact Quality

Inspect target or recent module artifacts for:

- semantic card or equivalent business context
- inline overlay semantics in module Markdown when overlays exist
- `owns` / `not_owns` / boundaries or durable intake/overlay source
- entry points, route surface, or extraction seeds
- source paths that point to real repo paths
- no obvious vendor/cache dominance in module metadata

Fail the gate if the module is only a generic summary and cannot support semantic routing.

#### 3. Community Safety

Inspect communities for the target module or recent rebuild:

```bash
rg -n "<module_or_repo>|source|degraded|skip_reason|no_graphify|jquery|Sizzle|bootstrap|\\.min\\.js|node_modules|\\.bin\\b|\\.obj\\b" ./Wiki/_data/communities
```

Passing behavior:

- graph-backed communities exist, or
- explicit degraded fallback communities exist with `source` and `degraded`

Failing behavior:

- `skip_reason=no_graphify_communities_available` with old stale communities silently reused
- vendor/generated files dominate top navigation
- query-side community hits hide `source` / `degraded`

#### 4. Semantic Query Smoke

Run at least one responsibility smoke. In focused mode, use:

```bash
/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge code query --wiki-root . --question "<module_name> 的主要責任是什麼？" --top 5 --extract-limit 4 --json
```

Open the newest evidence pack under:

```text
Wiki/_data/query_runs/
```

Required semantic fields:

```text
semantic.intake.question_type
semantic.routing.ambiguity
semantic.routing.needs_fixed_matrix
semantic.evidence_sufficiency.status
semantic.evidence_sufficiency.can_answer
semantic.evidence_sufficiency.next_step
```

#### 5. Eval Regression

For quick mode, evals are optional unless query runtime changed.

For full mode or runtime/shared pipeline changes, run:

```bash
/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge eval --wiki-root . --runtime graph
/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge eval --wiki-root . --runtime classic
```

#### 6. Search Loop Safety

Inspect recent query evidence or session logs only when a user reported a loop. The answer should state whether the agent repeated identical searches after:

- `BLOCKED`
- `repeated_exact_failure_warning`
- `idempotent_no_progress`
- same-result warning
- repeated zero-result warning

### Verdict Rules

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

### Handoff

- Use `llm-wiki-module-onboarding` (this subsection) when a new repo was never added.
- Use `llm-wiki-repo-infra-backfill` when one existing repo needs repair.
- Use `llm-wiki-pipeline-hardening` when the failure is shared generator/schema/runtime behavior.
- Use `llm-wiki-master-sync` (this subsection) when source freshness or master/head drift is the issue.
- Use `llm-wiki-query-semantic-workflow` (this subsection) when query evidence exists but the answering path is broad, ambiguous, or cross-repo.

See `references/verdict-matrix.md` for the full PASS/PARTIAL/FAIL decision matrix.

## Subsection: Semantic Workflow

Use this workflow when the main query returns partial/weak evidence, when the user asks a broad behavior/impact question, or when the answer needs an agent to reason across module routing, symbol hints, community hits, and direct source evidence.

### Required Runtime

Prefer the semantic graph runtime from the active Hermes wiki copy:

```bash
cd "/home/tedhsu/.hermes/data/llm-wiki"
/home/tedhsu/.hermes/hermes-agent/venv/bin/python -m llm_wiki_forge code query --wiki-root . --question "<question>" --top 5 --extract-limit 4 --json
```

If the runtime cannot execute in the current shell, use the fallback-to-source rules above and keep the same semantic gates manually.

### Evidence Pack Contract

After each query run, inspect:

```text
semantic.intake.question_type
semantic.intake.must_answer
semantic.intake.not_asking
semantic.routing.ambiguity
semantic.routing.needs_fixed_matrix
semantic.evidence_sufficiency.status
semantic.evidence_sufficiency.can_answer
semantic.evidence_sufficiency.next_step
routing.selected_modules
symbol_hints
navigation.extraction_plan
synthesis_inputs.direct_evidence
challenge.findings
```

Treat `semantic.*` as an agent-readable hypothesis and gate. Source code evidence still wins.

### Workflow

1. Run `llm-wiki-query` graph runtime first.
2. Read `semantic.intake`.
   - Use `question_type` to decide whether the answer is about formula, dispatch rule, API flow, writeback, route map, payment, address/geocoding, impact, or unknown.
   - Use `must_answer` as the checklist for what the final answer must cover.
   - Use `not_asking` to avoid a plausible but wrong neighboring module.
3. Read `semantic.routing`.
   - If `ambiguity=low`, continue with the top planned evidence.
   - If `ambiguity=medium/high`, verify the planned files before answering.
   - If `needs_fixed_matrix=true`, check the canonical four roots from the main query section before any negative conclusion.
4. Read `semantic.evidence_sufficiency`.
   - `strong`: answer from `direct_evidence`.
   - `partial`: read planned source files or answer only the directly proven part with uncertainty.
   - `weak`: do not synthesize a confident answer. Escalate to fixed-matrix verification, repo backfill, or pipeline hardening.
5. Compare `challenge.findings` with the semantic gate.
   - Any `semantic-route-ambiguous`, `fixed-matrix-recommended`, `weak-evidence-sufficiency`, or `partial-evidence-sufficiency` finding must be resolved or disclosed.
6. Answer with code evidence paths and method/class names unless the user explicitly wants PM-facing language.

### Sub-Agent Escalation

Use a source-inspection agent only when all are true:

- `semantic.evidence_sufficiency.status` is `partial` or `weak`.
- The evidence pack already names likely files, symbols, modules, or fixed-matrix roots.
- A focused source pass can improve the answer without changing wiki infrastructure.

Give the agent only the question, wiki root, evidence pack path, and candidate roots/files. Ask for:

```text
1. exact files and symbols inspected
2. direct code evidence summary
3. missing pieces that still need backfill/hardening
4. whether the original answer can be made safely
```

Do not ask a sub-agent to repair wiki infrastructure unless the user specifically wants backfill/hardening.

### Escalation Rules

Escalate to `llm-wiki-repo-infra-backfill` when:

- a single repo repeatedly lacks symbol hints, direct evidence, module markdown inline overlay, or non-stale fallback communities;
- `semantic.evidence_sufficiency.next_step` points to `expand_fixed_matrix_or_backfill_repo`;
- direct source verification succeeds but wiki metadata cannot route to it.

Escalate to `llm-wiki-pipeline-hardening` when:

- the same failure appears across more than one repo;
- generator/runtime/schema behavior causes stale communities, missing overlay inline, or missing semantic cards;
- a one-repo backfill proves a reusable fix.

Escalate to `llm-wiki-master-sync` (this subsection) when:

- source master/head changed and wiki artifacts must be refreshed;
- the issue is freshness, not missing infrastructure.

### Quality Gate

A final answer is acceptable only when:

- `semantic.evidence_sufficiency.can_answer=true`, or the answer explicitly states the missing evidence;
- direct source evidence supports any implementation claim;
- negative answers searched all relevant roots required by `needs_fixed_matrix`;
- PM-facing answers hide class/method/path jargon in the main body and keep evidence at the end.

See `references/semantic-evidence-contract.md` for the full semantic contract reference.

## Subsection: System Variable Setting

Use when source code contains a system-parameter lookup but the actual value is not in code. The caller must already have both inputs from source evidence:

- `VarGroup`
- `VarKey`

Do not guess either value. If one is missing, first continue the normal `llm-wiki-query` evidence flow to find it, or ask the user for the missing input.

### Command

Run from WSL/Linux with the Hermes Python runtime:

```bash
/home/tedhsu/.hermes/hermes-agent/venv/bin/python /home/tedhsu/.hermes/skills/llm-wiki-query/scripts/get_system_variable_setting.py --var-group "<VarGroup>" --var-key "<VarKey>" --json
```

The script calls the API with POST parameters:

```text
https://in-tgdswebapistage.taiwantaxi.com.tw/api/Core/Setting/GetSystemVariableSetting
```

Expected successful fields:

```json
{
  "VarGroup": "...",
  "VarKey": "...",
  "VarValue": "...",
  "VarText": "...",
  "Comment": "..."
}
```

### Answer Rules

1. Treat the API response as runtime configuration evidence, not source-code evidence.
2. In the answer, cite both pieces:
   - source evidence where `VarGroup` / `VarKey` came from
   - API response fields, especially `VarValue`, `VarText`, and `Comment`
3. If the API returns empty, non-JSON, timeout, or an error status, say the parameter value could not be verified from the stage API and include the requested `VarGroup` / `VarKey`.
4. Do not expose stack traces to Slack users. Summarize API errors in normal Traditional Chinese.
