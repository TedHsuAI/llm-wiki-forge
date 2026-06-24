from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llm_wiki_forge.runtime import run_packaged_module


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def kv(key: str, value: Any = "") -> str:
    return f"{key}={'' if value is None else value}"


def git(repo: Path, *args: str, env: dict[str, str] | None = None, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )


def require_under(path: Path, allowed_root: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    allowed = allowed_root.expanduser().resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise ValueError(f"{label} must be under {allowed}: {resolved}") from exc
    return resolved


def resolve_workspace_path(wiki_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.expanduser().resolve()
    return (wiki_root / path).resolve()


def load_repo_registry(wiki_root: Path, config_file: str = "Wiki/_meta/repo_sync/repos.json") -> tuple[dict[str, Any], Path]:
    config_path = resolve_workspace_path(wiki_root, config_file)
    if not config_path.exists():
        raise FileNotFoundError(f"Repo sync config not found: {config_path}")
    config = read_json(config_path)
    if not isinstance(config, dict):
        raise TypeError(f"Repo sync config must be a JSON object: {config_path}")
    return config, config_path


def find_repo_entry(config: dict[str, Any], repo_key: str) -> dict[str, Any]:
    matches = [repo for repo in config.get("repos", []) if isinstance(repo, dict) and repo.get("repoKey") == repo_key]
    if len(matches) != 1:
        raise KeyError(f"RepoKey {repo_key!r} was not found or is not unique")
    return matches[0]


def state_commit(state_file: Path) -> str:
    if not state_file.exists():
        return ""
    state = read_json(state_file)
    return str((state or {}).get("last_synced_commit") or "").strip()


def update_state_check_metadata(state_file: Path, repo_root: Path, tracked_branch: str, commit: str, status: str) -> None:
    state = read_json(state_file) if state_file.exists() else {}
    if not isinstance(state, dict):
        state = {}
    state["repo_root"] = str(repo_root)
    state["tracked_branch"] = tracked_branch
    state["last_checked_at"] = now_iso()
    state["last_checked_commit"] = commit
    state["last_checked_status"] = status
    write_json(state_file, state)


def cleanup_graphify_dirs(repo_root: Path) -> int:
    removed = 0
    for path in repo_root.rglob("graphify-out"):
        if path.is_dir():
            resolved = path.resolve()
            try:
                resolved.relative_to(repo_root.resolve())
            except ValueError:
                continue
            shutil.rmtree(resolved)
            removed += 1
    return removed


def dirty_status(repo_root: Path, allowed_globs: list[str]) -> tuple[list[str], list[str]]:
    result = git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git status failed")
    allowed: list[str] = []
    blocking: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip() if len(line) > 3 else ""
        if " -> " in path:
            path = path.split(" -> ")[-1].strip()
        normalized = path.replace("\\", "/")
        target = allowed if any(fnmatch.fnmatchcase(normalized, pattern) for pattern in allowed_globs) else blocking
        target.append(line)
    return allowed, blocking


def fetch_repo(repo_root: Path, repo_entry: dict[str, Any], git_auth: dict[str, Any]) -> subprocess.CompletedProcess:
    remote = str(repo_entry.get("gitRemote") or "origin")
    branch = str(repo_entry["trackedBranch"])
    env = os.environ.copy()
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
        }
    )
    first = git(repo_root, "fetch", "--quiet", remote, branch, env=env)
    if first.returncode == 0:
        return first

    password_file = Path(str(git_auth.get("passwordFile") or ""))
    private_key = Path(str(git_auth.get("privateKeyPath") or ""))
    if not password_file.exists() or not private_key.exists():
        return first

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, prefix="llm_wiki_git_askpass_", suffix=".sh") as fh:
        askpass = Path(fh.name)
        fh.write("#!/usr/bin/env sh\ncat \"$HERMES_GIT_PASSWORD_FILE\"\n")
    askpass.chmod(0o700)
    try:
        fallback_env = os.environ.copy()
        fallback_env.update(
            {
                "DISPLAY": "hermes-cron",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_ASKPASS": str(askpass),
                "SSH_ASKPASS": str(askpass),
                "SSH_ASKPASS_REQUIRE": "force",
                "HERMES_GIT_PASSWORD_FILE": str(password_file),
                "GIT_SSH_COMMAND": (
                    "ssh -o StrictHostKeyChecking=accept-new "
                    f"-o PreferredAuthentications=publickey -o BatchMode=no -i {private_key}"
                ),
            }
        )
        second = git(repo_root, "fetch", "--quiet", remote, branch, env=fallback_env)
        if second.returncode != 0:
            second.stdout = "\n".join(part for part in (first.stdout, second.stdout) if part)
            second.stderr = "\n".join(part for part in (first.stderr, second.stderr) if part)
        return second
    finally:
        try:
            askpass.unlink()
        except FileNotFoundError:
            pass


@dataclass
class Step:
    name: str
    status: str
    exit_code: int = 0
    log_path: str = ""
    message: str = ""
    started_at: str = ""
    ended_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "exit_code": self.exit_code,
            "log_path": self.log_path,
            "message": self.message,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


def _run_logged(
    *,
    name: str,
    wiki_root: Path,
    runs_dir: Path,
    timestamp: str,
    command: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> Step:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")
    log_path = runs_dir / f"full_sync_{timestamp}_{safe}.log"
    started = now_iso()
    result = subprocess.run(command, cwd=str(cwd) if cwd else str(wiki_root), env=env, text=True, capture_output=True, check=False)
    ended = now_iso()
    log_path.write_text((result.stdout or "") + (result.stderr or ""), encoding="utf-8")
    status = "completed" if result.returncode == 0 else "failed"
    message = "" if result.returncode == 0 else f"Command exited with {result.returncode}."
    return Step(name, status, result.returncode, str(log_path), message, started, ended)


def _run_packaged_logged(
    *,
    name: str,
    wiki_root: Path,
    runs_dir: Path,
    timestamp: str,
    python_path: Path,
    module: str,
    args: list[str],
) -> Step:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")
    log_path = runs_dir / f"full_sync_{timestamp}_{safe}.log"
    started = now_iso()
    result = run_packaged_module(
        python_path,
        module,
        args,
        cwd=wiki_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    ended = now_iso()
    log_path.write_text((result.stdout or "") + (result.stderr or ""), encoding="utf-8")
    status = "completed" if result.returncode == 0 else "failed"
    message = "" if result.returncode == 0 else f"Command exited with {result.returncode}."
    return Step(name, status, result.returncode, str(log_path), message, started, ended)


def _parse_diff_report(log_path: Path) -> Path | None:
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("diff report:"):
            return Path(line.split(":", 1)[1].strip())
        if line.startswith("report_json="):
            return Path(line.split("=", 1)[1].strip())
    return None


def _changed_file_count(diff_report: Path | None) -> int | None:
    if not diff_report or not diff_report.exists():
        return None
    data = read_json(diff_report)
    if isinstance(data, dict):
        if "changed_file_count" in data:
            return int(data.get("changed_file_count") or 0)
        summary = data.get("summary")
        if isinstance(summary, dict) and "changed_file_count" in summary:
            return int(summary.get("changed_file_count") or 0)
    return None


def _ensure_diff_markdown(diff_report: Path | None) -> Path | None:
    if not diff_report or not diff_report.exists():
        return None
    data = read_json(diff_report)
    if not isinstance(data, dict):
        return None
    markdown = diff_report.with_suffix(".md")
    changed_files = data.get("changed_files") or []
    if changed_files and isinstance(changed_files[0], dict):
        file_lines = [str(item.get("path") or "") for item in changed_files[:100]]
    else:
        file_lines = [str(item) for item in changed_files[:100]]
    lines = [
        f"# LLM Wiki Diff - {diff_report.stem.replace('diff_', '')}",
        "",
        f"- Repo root: {data.get('repo_root') or ''}",
        f"- Baseline: {data.get('baseline') or ''}",
        f"- Target ref: {data.get('target_ref') or ''}",
        f"- Target commit: {data.get('target_commit') or ''}",
        f"- Changed files: {data.get('changed_file_count') or len(changed_files)}",
        f"- Status: {data.get('status') or ''}",
        "",
        "## Changed Files",
        "",
    ]
    lines.extend(f"- `{path}`" for path in file_lines)
    if len(changed_files) > len(file_lines):
        lines.append(f"- ... {len(changed_files) - len(file_lines)} more")
    markdown.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return markdown


def _write_full_sync_report(
    *,
    wiki_root: Path,
    report_json: Path,
    report_markdown: Path,
    status: str,
    steps: list[Step],
    state_file: str,
    target_ref: str,
    diff_report: Path | None,
    diff_report_markdown: Path | None = None,
    accepted_baseline: bool,
    zero_diff: bool,
    failure_message: str = "",
) -> None:
    report = {
        "version": 1,
        "generated_at": now_iso(),
        "status": status,
        "failure_message": failure_message or None,
        "workspace_root": str(wiki_root),
        "state_file": state_file,
        "target_ref": target_ref,
        "accepted_baseline": accepted_baseline,
        "zero_diff": zero_diff,
        "diff_report_json": str(diff_report) if diff_report else "",
        "diff_report_markdown": str(diff_report_markdown) if diff_report_markdown else "",
        "steps": [step.as_dict() for step in steps],
        "runner": "llm_wiki_forge.repo_sync",
    }
    write_json(report_json, report)
    lines = [
        f"# Full LLM Wiki Master Sync - {report_json.stem.replace('full_sync_', '')}",
        "",
        f"- Status: {status}",
        f"- Target ref: {target_ref}",
        f"- Diff report JSON: {diff_report or ''}",
        f"- Accepted baseline: {accepted_baseline}",
        f"- Zero diff: {zero_diff}",
    ]
    if failure_message:
        lines.append(f"- Failure: {failure_message}")
    lines += [
        "",
        "| Step | Status | Log | Message |",
        "| --- | --- | --- | --- |",
    ]
    for step in steps:
        lines.append(f"| {step.name} | {step.status} | {step.log_path} | {step.message} |")
    report_markdown.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def run_full_sync(
    *,
    wiki_root: Path,
    repo_root: Path,
    state_file: str,
    python_path: Path,
    target_ref: str = "HEAD",
    accept_baseline: bool = False,
    community_top_per_module: int = 10,
) -> tuple[int, dict[str, Any]]:
    runs_dir = wiki_root / "Wiki" / "_meta" / "master_sync_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_json = runs_dir / f"full_sync_{timestamp}.json"
    report_markdown = runs_dir / f"full_sync_{timestamp}.md"
    steps: list[Step] = []

    diff_step = _run_packaged_logged(
        name="diff-plan",
        wiki_root=wiki_root,
        runs_dir=runs_dir,
        timestamp=timestamp,
        python_path=python_path,
        module="scripts.repo_sync.diff_wiki",
        args=["--wiki-root", str(wiki_root), "--repo-root", str(repo_root), "--state", state_file, "--target-ref", target_ref],
    )
    steps.append(diff_step)
    if diff_step.exit_code != 0:
        _write_full_sync_report(
            wiki_root=wiki_root,
            report_json=report_json,
            report_markdown=report_markdown,
            status="failed",
            steps=steps,
            state_file=state_file,
            target_ref=target_ref,
            diff_report=None,
            diff_report_markdown=None,
            accepted_baseline=False,
            zero_diff=False,
            failure_message="diff-plan failed",
        )
        return diff_step.exit_code, {"full_sync_report_json": str(report_json), "full_sync_report_markdown": str(report_markdown), "status": "failed"}

    diff_report = _parse_diff_report(Path(diff_step.log_path))
    diff_markdown = _ensure_diff_markdown(diff_report)
    changed_count = _changed_file_count(diff_report)
    if changed_count == 0:
        for name in (
            "refresh-scope-symbols",
            "rebuild-modules-graphify",
            "rebuild-communities",
            "apply-curated-overlays",
            "eval-graph",
            "eval-classic",
            "invalidate-slack-helper-cache",
            "accept-baseline",
        ):
            steps.append(Step(name, "skipped", message="No changed files were detected.", started_at=now_iso(), ended_at=now_iso()))
        _write_full_sync_report(
            wiki_root=wiki_root,
            report_json=report_json,
            report_markdown=report_markdown,
            status="completed-noop",
            steps=steps,
            state_file=state_file,
            target_ref=target_ref,
            diff_report=diff_report,
            diff_report_markdown=diff_markdown,
            accepted_baseline=False,
            zero_diff=True,
        )
        return 0, {
            "full_sync_report_json": str(report_json),
            "full_sync_report_markdown": str(report_markdown),
            "diff_report_json": str(diff_report or ""),
            "diff_report_markdown": str(diff_markdown or ""),
            "accepted_baseline": False,
            "status": "completed-noop",
        }

    for step in (
        _run_packaged_logged(
            name="refresh-scope-inventory",
            wiki_root=wiki_root,
            runs_dir=runs_dir,
            timestamp=timestamp,
            python_path=python_path,
            module="scripts.update_wiki",
            args=["--wiki-root", str(wiki_root)],
        ),
        _run_packaged_logged(
            name="rebuild-modules-graphify",
            wiki_root=wiki_root,
            runs_dir=runs_dir,
            timestamp=timestamp,
            python_path=python_path,
            module="scripts.generate_module_wiki",
            args=["--wiki-root", str(wiki_root)],
        ),
        _run_packaged_logged(
            name="rebuild-communities",
            wiki_root=wiki_root,
            runs_dir=runs_dir,
            timestamp=timestamp,
            python_path=python_path,
            module="scripts.query_runtime.community_builder",
            args=["--wiki-root", str(wiki_root), "--top-per-module", str(community_top_per_module)],
        ),
    ):
        steps.append(step)
        if step.exit_code != 0:
            _write_full_sync_report(
                wiki_root=wiki_root,
                report_json=report_json,
                report_markdown=report_markdown,
                status="failed",
                steps=steps,
                state_file=state_file,
                target_ref=target_ref,
                diff_report=diff_report,
                diff_report_markdown=diff_markdown,
                accepted_baseline=False,
                zero_diff=False,
                failure_message=f"{step.name} failed",
            )
            return step.exit_code, {"full_sync_report_json": str(report_json), "full_sync_report_markdown": str(report_markdown), "status": "failed"}

    optional_steps = [
        ("eval-graph", "scripts.query_runtime.eval_queries", ["--wiki-root", str(wiki_root), "--runtime", "graph"]),
        ("eval-classic", "scripts.query_runtime.eval_queries", ["--wiki-root", str(wiki_root), "--runtime", "classic"]),
    ]
    for name, module, args in optional_steps:
        step = _run_packaged_logged(
            name=name,
            wiki_root=wiki_root,
            runs_dir=runs_dir,
            timestamp=timestamp,
            python_path=python_path,
            module=module,
            args=args,
        )
        steps.append(step)
        if step.exit_code != 0:
            _write_full_sync_report(
                wiki_root=wiki_root,
                report_json=report_json,
                report_markdown=report_markdown,
                status="failed",
                steps=steps,
                state_file=state_file,
                target_ref=target_ref,
                diff_report=diff_report,
                diff_report_markdown=diff_markdown,
                accepted_baseline=False,
                zero_diff=False,
                failure_message=f"{name} failed",
            )
            return step.exit_code, {"full_sync_report_json": str(report_json), "full_sync_report_markdown": str(report_markdown), "status": "failed"}

    accepted = False
    if accept_baseline:
        accept_step = _run_packaged_logged(
            name="accept-baseline",
            wiki_root=wiki_root,
            runs_dir=runs_dir,
            timestamp=timestamp,
            python_path=python_path,
            module="scripts.repo_sync.diff_wiki",
            args=[
                "--wiki-root",
                str(wiki_root),
                "--repo-root",
                str(repo_root),
                "--state",
                state_file,
                "--target-ref",
                target_ref,
                "--accept-baseline",
            ],
        )
        steps.append(accept_step)
        if accept_step.exit_code != 0:
            _write_full_sync_report(
                wiki_root=wiki_root,
                report_json=report_json,
                report_markdown=report_markdown,
                status="failed",
                steps=steps,
                state_file=state_file,
                target_ref=target_ref,
                diff_report=diff_report,
                diff_report_markdown=diff_markdown,
                accepted_baseline=False,
                zero_diff=False,
                failure_message="accept-baseline failed",
            )
            return accept_step.exit_code, {"full_sync_report_json": str(report_json), "full_sync_report_markdown": str(report_markdown), "status": "failed"}
        accepted = True
    else:
        steps.append(Step("accept-baseline", "skipped", message="--accept-baseline was not supplied.", started_at=now_iso(), ended_at=now_iso()))

    _write_full_sync_report(
        wiki_root=wiki_root,
        report_json=report_json,
        report_markdown=report_markdown,
        status="completed",
        steps=steps,
        state_file=state_file,
        target_ref=target_ref,
        diff_report=diff_report,
        diff_report_markdown=diff_markdown,
        accepted_baseline=accepted,
        zero_diff=False,
    )
    return 0, {
        "full_sync_report_json": str(report_json),
        "full_sync_report_markdown": str(report_markdown),
        "diff_report_json": str(diff_report or ""),
        "diff_report_markdown": str(diff_markdown or ""),
        "accepted_baseline": accepted,
        "status": "completed",
    }


def invoke_repo_sync(
    *,
    wiki_root: Path,
    repo_key: str,
    python_path: Path,
    source_root: Path,
    config_file: str = "Wiki/_meta/repo_sync/repos.json",
    skip_fetch: bool = False,
    dry_run: bool = False,
    accept_baseline: bool = True,
) -> int:
    try:
        wiki_root = wiki_root.expanduser().resolve()
        source_root = source_root.expanduser().resolve()
        config, _config_path = load_repo_registry(wiki_root, config_file)
        repo_entry = find_repo_entry(config, repo_key)
        repo_root = require_under(resolve_workspace_path(wiki_root, str(repo_entry["repoRoot"])), source_root, "repo_root")
        state_file_spec = str(repo_entry["stateFile"])
        state_file = resolve_workspace_path(wiki_root, state_file_spec)
        tracked_branch = str(repo_entry["trackedBranch"])
        git_remote = str(repo_entry.get("gitRemote") or "origin")
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not (repo_root / ".git").is_dir():
        print(f"Repo root not found or not a git repo: {repo_root}", file=sys.stderr)
        return 2

    graphify_cleanup = cleanup_graphify_dirs(repo_root)
    current_branch_result = git(repo_root, "branch", "--show-current")
    current_branch = current_branch_result.stdout.strip()
    if current_branch != tracked_branch:
        print(kv("result_status", "BLOCKED"))
        print(kv("repo_key", repo_key))
        print(kv("tracked_branch", tracked_branch))
        print(kv("current_branch", current_branch))
        print(f"Repo '{repo_key}' is on branch '{current_branch}', expected '{tracked_branch}'.", file=sys.stderr)
        return 4

    allowed_dirty, blocking_dirty = dirty_status(repo_root, list(repo_entry.get("allowDirtyPathGlobs") or []))
    if blocking_dirty:
        print(kv("result_status", "BLOCKED"))
        print(kv("repo_key", repo_key))
        print(kv("tracked_branch", tracked_branch))
        print(kv("graphify_cleanup_removed_count", graphify_cleanup))
        print(kv("blocking_dirty_count", len(blocking_dirty)))
        print(kv("blocking_dirty_entries_sample", " || ".join(blocking_dirty[:10])))
        print(f"Repo '{repo_key}' has blocking working tree changes.", file=sys.stderr)
        return 5

    before = git(repo_root, "rev-parse", "HEAD").stdout.strip()
    if not skip_fetch:
        fetch = fetch_repo(repo_root, repo_entry, config.get("gitAuth") or {})
        if fetch.returncode != 0:
            print(kv("result_status", "FETCH_FAILED"))
            print(kv("repo_key", repo_key))
            print(kv("tracked_branch", tracked_branch))
            print(kv("before_commit", before))
            print(kv("graphify_cleanup_removed_count", graphify_cleanup))
            print(kv("fetch_exit_code", fetch.returncode))
            print(kv("fetch_output", ((fetch.stdout or "") + (fetch.stderr or "")).replace("\n", " || ")))
            return fetch.returncode

    remote_ref = f"{git_remote}/{tracked_branch}"
    remote_commit = git(repo_root, "rev-parse", remote_ref).stdout.strip()
    baseline_commit = state_commit(state_file)
    baseline_needs_sync = not baseline_commit or baseline_commit != before

    if before == remote_commit and not baseline_needs_sync:
        update_state_check_metadata(state_file, repo_root, tracked_branch, remote_commit, "no-change")
        print(kv("result_status", "NO_CHANGE"))
        print(kv("repo_key", repo_key))
        print(kv("repo_root", repo_root))
        print(kv("tracked_branch", tracked_branch))
        print(kv("state_file", state_file_spec))
        print(kv("baseline_commit", baseline_commit))
        print(kv("local_head", before))
        print(kv("remote_head", remote_commit))
        print(kv("graphify_cleanup_removed_count", graphify_cleanup))
        print(kv("allowed_dirty_count", len(allowed_dirty)))
        return 0

    ancestor = git(repo_root, "merge-base", "--is-ancestor", "HEAD", remote_ref)
    if ancestor.returncode != 0:
        print(kv("result_status", "DIVERGED"))
        print(kv("repo_key", repo_key))
        print(kv("repo_root", repo_root))
        print(kv("tracked_branch", tracked_branch))
        print(kv("state_file", state_file_spec))
        print(kv("before_commit", before))
        print(kv("remote_commit", remote_commit))
        print(kv("graphify_cleanup_removed_count", graphify_cleanup))
        return 3

    if dry_run:
        reason = "BASELINE_BEHIND" if before == remote_commit and baseline_needs_sync else "REMOTE_AHEAD"
        print(kv("result_status", "DRY_RUN"))
        print(kv("repo_key", repo_key))
        print(kv("repo_root", repo_root))
        print(kv("tracked_branch", tracked_branch))
        print(kv("state_file", state_file_spec))
        print(kv("baseline_commit", baseline_commit))
        print(kv("before_commit", before))
        print(kv("remote_commit", remote_commit))
        print(kv("sync_reason", reason))
        print(kv("graphify_cleanup_removed_count", graphify_cleanup))
        return 0

    after = before
    if before != remote_commit:
        merge = git(repo_root, "merge", "--ff-only", remote_ref)
        if merge.returncode != 0:
            print(kv("result_status", "UPDATE_FAILED"))
            print(kv("repo_key", repo_key))
            print(kv("tracked_branch", tracked_branch))
            print(kv("before_commit", before))
            print(kv("remote_commit", remote_commit))
            print(kv("merge_output", ((merge.stdout or "") + (merge.stderr or "")).replace("\n", " || ")))
            return merge.returncode
        after = git(repo_root, "rev-parse", "HEAD").stdout.strip()

    sync_exit, full_sync = run_full_sync(
        wiki_root=wiki_root,
        repo_root=repo_root,
        state_file=state_file_spec,
        python_path=python_path,
        target_ref="HEAD",
        accept_baseline=accept_baseline,
    )
    post_cleanup = cleanup_graphify_dirs(repo_root)
    total_cleanup = graphify_cleanup + post_cleanup

    if sync_exit != 0:
        update_state_check_metadata(state_file, repo_root, tracked_branch, remote_commit, "sync-failed")
        print(kv("result_status", "SYNC_FAILED"))
        print(kv("repo_key", repo_key))
        print(kv("tracked_branch", tracked_branch))
        print(kv("before_commit", before))
        print(kv("after_commit", after))
        print(kv("remote_commit", remote_commit))
        print(kv("graphify_cleanup_removed_count", total_cleanup))
        print(kv("full_sync_report_json", full_sync.get("full_sync_report_json", "")))
        print(kv("full_sync_report_markdown", full_sync.get("full_sync_report_markdown", "")))
        print(kv("diff_report_json", full_sync.get("diff_report_json", "")))
        print(kv("full_sync_status", full_sync.get("status", "")))
        return sync_exit

    update_state_check_metadata(state_file, repo_root, tracked_branch, remote_commit, "updated")
    print(kv("result_status", "UPDATED"))
    print(kv("repo_key", repo_key))
    print(kv("repo_root", repo_root))
    print(kv("tracked_branch", tracked_branch))
    print(kv("state_file", state_file_spec))
    print(kv("baseline_commit", baseline_commit))
    print(kv("before_commit", before))
    print(kv("after_commit", after))
    print(kv("remote_commit", remote_commit))
    print(kv("graphify_cleanup_removed_count", total_cleanup))
    print(kv("full_sync_report_json", full_sync.get("full_sync_report_json", "")))
    print(kv("full_sync_report_markdown", full_sync.get("full_sync_report_markdown", "")))
    print(kv("diff_report_json", full_sync.get("diff_report_json", "")))
    print(kv("diff_report_markdown", full_sync.get("diff_report_markdown", "")))
    print(kv("full_sync_status", full_sync.get("status", "")))
    print(kv("accepted_baseline", full_sync.get("accepted_baseline", "")))
    return 0
