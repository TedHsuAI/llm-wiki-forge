# LLM Wiki Forge Sync Timeout Pitfall

## Session Context

- **Session date**: 2026-06-11
- **Trigger**: Scheduled cron job running `llm_wiki_forge sync`
- **Command**: `llm_wiki_forge sync --wiki-root "/home/tedhsu/llm-wiki/dispatch" --source-root "/home/tedhsu/codebases/dispatch" --repo-key "RD.TGDS" --accept-baseline`

## Problem

The command timed out after 300 seconds (exit code 124) with **no stdout output** and **no result_status** produced. The existing `master_sync_state.json` still showed the last accepted baseline from 2026-05-07, confirming no baseline was accepted by this run.

## Diagnosis Steps

1. Run the command with a 300s timeout — it timed out with exit code 124.
2. Check `Wiki/_meta/master_sync_runs/` for new files — none were created after the existing `diff_20260611_055017` artifacts.
3. Check `Wiki/_meta/master_sync_state.json` — still shows `accepted` status with last commit from 2026-05-07.
4. Conclusion: the sync operation did not complete; no result_status was produced.

## Result Handling Rules (from llm-wiki-query skill)

When `llm_wiki_forge sync` completes, handle by result_status:

- **NO_CHANGE**: reply exactly `[SILENT]`
- **UPDATED**: report repo_key, tracked_branch, before_commit, after_commit, graphify_cleanup_removed_count, full_sync_report_markdown, diff_report_markdown, full_sync_status, accepted_baseline
- **DRY_RUN**: report as dry run with before_commit and remote_commit
- **BLOCKED/FETCH_FAILED/DIVERGED/UPDATE_FAILED/SYNC_FAILED**: summarize failure and include report paths

## Timeout Handling (NEW)

When the command times out (exit code 124) with no result_status:

1. Do NOT assume NO_CHANGE or [SILENT] — the command did not complete.
2. Report the timeout explicitly: exit code 124, no result_status produced, no new files in Wiki/_meta/master_sync_runs/.
3. Check the existing master_sync_state.json to confirm no baseline was accepted.
4. Recommend re-running with a longer timeout (600s-900s) or splitting into --dry-run first, then accept separately.
5. Do not narrate internal retry logic to the user; just state the timeout and the recommended next step.

### 2026-06-15 run

- Command timed out at 300s with exit code 124, no stdout, no result_status.
- Latest diff before timeout: `diff_20260615_061019` — 9 changed files in `TGDS.WebAPI` (CalcMeterPrice.cs, GetHistoryAddr.cs, SearchWorkPaper.cs, GISController.cs, LogRequestAndResponseHandler.cs, BatAASAuthTransaction.cs, HistoryAddr.cs, ElasticAPI.cs, JobServices.cs).
- Baseline: `a7f28c96e8fae44c62389390d432d5d4a85ef16f`
- Target commit: `e384a7779ef3d690bf911237f0b466c742a1a552`
- `master_sync_state.json` still points to 2026-05-07 baseline (`7ad0f74cdf03350374438a33a1800fe6d11b313f`) — no baseline accepted.
- No new files in `Wiki/_meta/master_sync_runs/` after the diff artifacts.

### 2026-06-16 run (~22:00 UTC / cron — current session)

- Command timed out at 300s with exit code 124, no stdout, no result_status.
- Latest diff before timeout: `diff_20260616_140021` — 10 changed files in `TGDS.WebAPI` (CalcMeterPrice.cs, Query.cs, GetHistoryAddr.cs, SearchWorkPaper.cs, GISController.cs, LogRequestAndResponseHandler.cs, BatAASAuthTransaction.cs, HistoryAddr.cs, ElasticAPI.cs, JobServices.cs).
- Baseline: `a7f28c96e8fae44c62389390d432d5d4a85ef16f`
- Target commit: `dc185817c2ee89006199743653a6b1d71e58630e`
- `master_sync_state.json` still points to 2026-05-07 baseline (`7ad0f74cdf03350374438a33a1800fe6d11b313f`) — no baseline accepted.
- No new files in `Wiki/_meta/master_sync_runs/` after the diff artifacts.

### 2026-06-12 earlier run

- Latest prior diff: `diff_20260612_070108` — 1 changed file (TDC/SvcWorker.cs).
- Baseline: `cc35f192857543ca23e448a2791f6f9e67122f0b`
- Target commit: `39e26e6d37819f170692d11fa1eb8cd74fbf9e5`
- Status: `diff-ready` (not yet accepted)

### 2026-06-17 run A (~14:28 UTC / cron)

- Command timed out at 300s with exit code 124, no stdout, no result_status.
- Latest diff before timeout: `diff_20260617_054009` — 3 changed files in `TGDS.WebAPI` (LaunchPayBack.cs controller, LaunchPayBack.cs model, PaymentControllerTests.cs).
- Baseline: `7ad0f74cdf03350374438a33a1800fe6d11b313f` (2026-05-07)
- Target commit: `df0678c3bab002fe0a2cdc32b8ca9257840e1358`
- `master_sync_state.json` still points to 2026-05-07 baseline — no baseline accepted.
- No new files in `Wiki/_meta/master_sync_runs/` after the diff artifacts.

### 2026-06-17 run B (~15:44 UTC / cron — current session)

- Command timed out at 300s with exit code 124, no stdout, no result_status.
- Latest diff before timeout: `diff_20260617_063033` — 3 changed files in `TGDS.WebAPI` (LaunchPayBack.cs controller, LaunchPayBack.cs model, PaymentControllerTests.cs).
- Baseline: `f24941222af0e30d04eaf53cd3187a4055d07a24` (more recent than run A's baseline)
- Target commit: `df0678c3bab002fe0a2cdc32b8ca9257840e1358`
- `master_sync_state.json` still points to 2026-05-07 baseline — no baseline accepted.
- Diff plan log and scope inventory refresh log were generated, but no acceptance artifacts followed.
- Filesystem evidence: `diff_20260617_063033.json`, `diff_20260617_063033.md`, `full_sync_20260617_063033_diff_plan.log`, and `full_sync_20260617_063033_refresh_scope_inventory.log` all exist; no post-acceptance files were created.

### 2026-06-19 run (DispatchRule repo)

- Command timed out at 300s with exit code 124, no stdout, no result_status.
- Latest diff before timeout: `diff_20260618_183310` — 15 changed files in `DispatchRule.WebAPI` (DispatchBatchRepository.cs, DispatchBatchServices.cs, ETAScoreCalculator.cs, ETAReguFilter.cs, ComputeRouteMatrixReguFilter.cs, SpeciallyJobReguFilter.cs, JobConditionService.cs, MyStartupHangfireJobs.cs, JOB_ExecVEH.cs DTO, plus 6 test files).
- Baseline: `9379babd805b4f4b7b9abc3e7490cbb5d69a48b8`
- Target commit: `502270b9be96b09eb97ea15119b96acfcc5b6c03`
- `master_sync_state.json` still points to 2026-05-07 baseline (`7ad0f74cdf03350374438a33a1800fe6d11b313f`) — no baseline accepted.
- No new files in `Wiki/_meta/master_sync_runs/` after the diff artifacts.
- Scope inventory refresh produced 11 items.

### 2026-06-22 run A (~11:00 UTC+8 / cron)

- Command timed out at 300s with exit code 124, no stdout, no result_status.
- Latest diff before timeout: `diff_20260622_031110` — 5 changed files in `TGDS.WebAPI` and `BaseClass` (Estimated.cs, TaxiFareCalc.cs, TaxiPlusV2Service.cs, TGDS.WebAPI.csproj, DynamicExt.cs).
- Baseline: `24305951990428445ba5168842b29ac7ae570224` (2026-05-07)
- Target commit: `13674ef1c7660090ff84c558b4d4df7099d43ab1`
- `repo_sync/RD.TGDS.json` still shows `last_synced_commit` = baseline, `last_checked_status` = "no-change" — no baseline accepted.
- Previous completed run in same day: `full_sync_20260622_021604` completed in ~6m9s with 21 changed files and all steps completed.
- No new files in `Wiki/_meta/master_sync_runs/` after the diff artifacts.

### 2026-06-22 run B (~13:40 UTC+8 / cron)

- Command timed out at 300s with exit code 124, no stdout, no result_status.
- Latest diff before timeout: `diff_20260622_054029` — 15 changed files (5 source files + 10 bin/Release binaries: BaseClass.XML, BaseClass.dll, BaseClass.pdb, CommonDTO.XML, CommonDTO.dll, CommonDTO.pdb, DataTier.dll, DataTier.pdb).
- Baseline: `24305951990428445ba5168842b29ac7ae570224`
- Target commit: `b8cded9e6e3bc1be6f6465ee414c7721d6bc6c37`
- `master_sync_state.json` still points to 2026-05-07 baseline (`7ad0f74cdf03350374438a33a1800fe6d11b313f`) — no baseline accepted.
- No new files in `Wiki/_meta/master_sync_runs/` after the diff artifacts.
- **Notable**: This diff includes 10 binary files (.dll/.pdb/.XML) in `BaseClass/bin/Release/`. Binaries should be excluded from sync scope — they inflate file count and may slow diff computation.
- **Diff plan log**: `full_sync_20260622_054029_diff_plan.log` and `full_sync_20260622_054029_refresh_scope_inventory.log` exist; no acceptance artifacts followed.

### 2026-06-22 run C (~14:24 UTC+8 / cron)

- Command timed out at 300s with exit code 124, no stdout, no result_status.
- Latest diff before timeout: `diff_20260622_061422` — 15 changed files (5 source files + 10 bin/Release binaries: BaseClass.XML, BaseClass.dll, BaseClass.pdb, CommonDTO.XML, CommonDTO.dll, CommonDTO.pdb, DataTier.dll, DataTier.pdb).
- Baseline: `7ad0f74cdf03350374438a33a1800fe6d11b313f` (2026-05-07)
- Target commit: `b8cded9e6e3bc1be6f6465ee414c7721d6bc6c37`
- `master_sync_state.json` still points to 2026-05-07 baseline — no baseline accepted.
- No new files in `Wiki/_meta/master_sync_runs/` after the diff artifacts.
- **Diff plan log**: `full_sync_20260622_061422_diff_plan.log` and `full_sync_20260622_061422_refresh_scope_inventory.log` exist; no acceptance artifacts followed.
- **Same binary file pattern** as run B — 10 bin/Release binaries in `BaseClass/bin/Release/` are consistently included in diffs.

### 2026-06-22 run D (~16:59 UTC+8 / cron — current session)

- Command timed out at 300s with exit code 124, no stdout, no result_status.
- Latest diff before timeout: `diff_20260622_064014` — 15 changed files (5 source files + 10 bin/Release binaries: BaseClass.XML, BaseClass.dll, BaseClass.pdb, CommonDTO.XML, CommonDTO.dll, CommonDTO.pdb, DataTier.dll, DataTier.pdb).
- Baseline: `24305951990428445ba5168842b29ac7ae570224` (accepted by `full_sync_20260622_021604`)
- Target commit: `b8cded9e6e3bc1be6f6465ee414c7721d6bc6c37`
- `master_sync_state.json` still points to 2026-05-07 baseline (`7ad0f74cdf03350374438a33a1800fe6d11b313f`) — no baseline accepted by this run.
- No new files in `Wiki/_meta/master_sync_runs/` after the diff artifacts.
- **Diff plan log**: `full_sync_20260622_064014_diff_plan.log` and `full_sync_20260622_064014_refresh_scope_inventory.log` exist; no acceptance artifacts followed.
- **Same binary file pattern** — 10 bin/Release binaries in `BaseClass/bin/Release/` consistently included.
- **Note**: This is the 4th timeout on the same day (runs A–D), all with the same 300s timeout and same binary file inclusion pattern. The `full_sync_20260622_021604` completed in ~6m9s, confirming the 300s timeout is insufficient.

### 2026-06-22 run E (~23:06 UTC+8 / cron)

- Command timed out at 300s with exit code 124, no stdout, no result_status.
- Latest diff before timeout: `diff_20260622_133029` — 20 changed files.
- Baseline: `24305951990428445ba5168842b29ac7ae570224` (accepted by `full_sync_20260622_021604`).
- Target commit: `240ea5cf97aa6dd9ae664da48569474e46e354bf`.
- `master_sync_state.json` still points to 2026-05-07 baseline (`7ad0f74cdf03350374438a33a1800fe6d11b313f`) — no baseline accepted.
- No new files in `Wiki/_meta/master_sync_runs/` after the diff artifacts.
- **This is the 5th timeout on June 22** (runs A–E). All with the same 300s timeout.

### 2026-06-23 run (~10:34 UTC+8 / cron)

- Command timed out at 300s with exit code 124, no stdout, no result_status.
- Latest diff before timeout: `diff_20260623_013110` — 3 changed files in `TDC` (AssemblyInfo.cs x2, SvcWorker.cs).
- Baseline: `240ea5cf97aa6dd9ae664da48569474e46e354bf` (accepted by `full_sync_20260622_021604`).
- Target commit: `34e50a3f633be9434fc29ab09a7c5d4fd9290668`.
- `repo_sync/RD.TGDS.json` still shows `last_synced_commit` = baseline, `last_checked_status` = "no-change" — no baseline accepted.
- No new files in `Wiki/_meta/master_sync_runs/` after the diff artifacts.
- **Notable**: This diff has only 3 source files (no binaries), yet still timed out. Confirms the bottleneck is not just file count but accumulated commit history gap and WSL-mounted source root performance.
- **Scope inventory**: 11 items.
- **Diff plan log**: `full_sync_20260623_013110_diff_plan.log` and `full_sync_20260623_013110_refresh_scope_inventory.log` exist; no acceptance artifacts followed.

### 2026-06-23 run B (~10:49 UTC+8 / cron — current session)

- Command timed out at 300s with exit code 124, no stdout, no result_status.
- Latest diff before timeout: `diff_20260623_024103` — 3 changed files in `TDC` (AssemblyInfo.cs x2, SvcWorker.cs).
- Baseline: `240ea5cf97aa6dd9ae664da48569474e46e354bf` (accepted by `full_sync_20260622_021604`).
- Target commit: `34e50a3f633be9434fc29ab09a7c5d4fd9290668`.
- `master_sync_state.json` still points to 2026-05-07 baseline (`7ad0f74cdf03350374438a33a1800fe6d11b313f`) — no baseline accepted.
- No new files in `Wiki/_meta/master_sync_runs/` after the diff artifacts.
- **Scope inventory**: 11 items.
- **Diff plan log**: `full_sync_20260623_024103_diff_plan.log` and `full_sync_20260623_024103_refresh_scope_inventory.log` exist; no acceptance artifacts followed.
- **Same 3-file diff as run A** — same baseline, same target commit, same changed files. The diff plan was regenerated but the full sync still timed out.

### 2026-06-23 run B (~14:59 UTC+8 / cron — current session)

- Command timed out at 300s with exit code 124, no stdout, no result_status.
- Latest diff before timeout: `diff_20260623_065432` — 3 changed files in `TDC` (AssemblyInfo.cs x2, SvcWorker.cs).
- Baseline: `240ea5cf97aa6dd9ae664da48569474e46e354bf` (accepted by `full_sync_20260622_021604`).
- Target commit: `34e50a3f633be9434fc29ab09a7c5d4fd9290668`.
- `master_sync_state.json` still points to 2026-05-07 baseline (`7ad0f74cdf03350374438a33a1800fe6d11b313f`) — no baseline accepted.
- No new files in `Wiki/_meta/master_sync_runs/` after the diff artifacts.
- **Diff plan log**: `full_sync_20260623_065432_diff_plan.log` and `full_sync_20260623_065432_refresh_scope_inventory.log` exist; no acceptance artifacts followed.
- **Same 3-file diff as earlier runs** — same baseline, same target commit, same changed files. The diff plan was regenerated but the full sync still timed out.

### Root cause pattern

When the gap between accepted baseline and HEAD grows large (e.g., 2026-05-07 to 2026-06-23 = ~47 days), the diff computation and module rebuild can exceed 300s. This is now a **recurring pattern across 10+ sessions** (June 11, 12, 15, 16, 17 x2, 19, 22 x5, and 23 x3). The file count per diff run varies (1 → 16 → 9 → 10 → 3 → 15 → 5 → 20 → 3) but the timeout is consistent, suggesting the bottleneck is not just file count but also the accumulated commit history and WSL-mounted source root performance.

**Timing evidence**: A full sync with 21 changed files completed in ~6m9s (June 22 02:16–02:22 UTC+8). The `rebuild-modules-graphify` step alone took ~6 minutes. A 300s timeout is insufficient for any non-trivial sync.

**Critical finding (June 23)**: Even a diff with only 3 source files (no binaries) timed out at 300s. This confirms the bottleneck is not just file count but accumulated commit history gap and WSL-mounted source root performance.

**Mitigation**: 
1. Run `--dry-run` first to validate the diff plan before `--accept-baseline`.
2. Increase cron timeout to 600s–900s (minimum 7 minutes) for both `RD.TGDS` and `DispatchRule` repos.
3. Consider accepting the baseline more frequently (e.g., weekly) to keep the gap small.
4. If the gap is too large, consider a manual `git reset --hard` to an earlier point and re-sync incrementally.

## Key Files

- `Wiki/_meta/master_sync_state.json` — sync state and last accepted baseline
- `Wiki/_meta/master_sync_runs/diff_20260612_070108.json` — latest diff report
- `Wiki/_meta/master_sync_runs/diff_20260612_070108.md` — latest diff markdown
- `Wiki/_meta/master_sync_runs/full_sync_20260612_070108_diff_plan.log` — sync plan log
- `Wiki/_meta/master_sync_runs/full_sync_20260612_070108_refresh_scope_inventory.log` — scope inventory log