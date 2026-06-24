#!/usr/bin/env python3
"""Hermes maintenance tools for Forge-owned LLM Wiki build/sync flows."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.registry import registry, tool_error, tool_result


DEFAULT_TIMEOUT_SECONDS = 900


def _python_bin(args: dict[str, Any]) -> str:
    return (
        str(args.get("python") or "").strip()
        or os.environ.get("HERMES_LLM_WIKI_FORGE_PYTHON")
        or os.environ.get("HERMES_LLM_WIKI_PYTHON")
        or sys.executable
    )


def _required_path(args: dict[str, Any], field: str, env_name: str) -> Path:
    value = str(args.get(field) or os.environ.get(env_name) or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return Path(value).expanduser()


def _wiki_root(args: dict[str, Any]) -> Path:
    return _required_path(args, "wiki_root", "HERMES_LLM_WIKI_ROOT")


def _source_root(args: dict[str, Any]) -> Path:
    return _required_path(args, "source_root", "HERMES_LLM_WIKI_SOURCE_ROOT")


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except Exception:
        return False


def _forge_available() -> bool:
    return True


def _run_forge(args: dict[str, Any], command_args: list[str], timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    command = [_python_bin(args), "-m", "llm_wiki_forge", *command_args]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _kv_stdout(stdout: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in (stdout or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed[key.strip()] = value.strip()
    return parsed


def llm_wiki_forge_sync_tool(args: dict[str, Any], **_kwargs) -> str:
    repo_key = str(args.get("repo_key") or "").strip()
    if not repo_key:
        return tool_error("repo_key is required")
    try:
        wiki_root = _wiki_root(args)
        source_root = _source_root(args)
    except ValueError as exc:
        return tool_error(str(exc))

    command_args = [
        "update",
        "--wiki-root",
        str(wiki_root),
        "--source-root",
        str(source_root),
        "--repo-key",
        repo_key,
    ]
    if not bool(args.get("accept_baseline", True)):
        command_args.append("--no-accept-baseline")
    if bool(args.get("skip_fetch", False)):
        command_args.append("--skip-fetch")
    if bool(args.get("dry_run", False)):
        command_args.append("--dry-run")

    try:
        result = _run_forge(args, command_args, timeout=int(args.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS))
    except subprocess.TimeoutExpired:
        return tool_error("llm-wiki forge sync timed out", next_action="check_cron_or_run_narrow_diagnostic")
    except Exception as exc:
        return tool_error(str(exc), next_action="verify_llm_wiki_forge_install")

    parsed = _kv_stdout(result["stdout"])
    return tool_result(
        {
            "next_action": "report_status",
            "repo_key": repo_key,
            "result_status": parsed.get("result_status"),
            "parsed": parsed,
            "exit_code": result["exit_code"],
            "stdout": result["stdout"][-12000:],
            "stderr": result["stderr"][-4000:],
            "command": result["command"],
        }
    )


def llm_wiki_forge_repo_add_tool(args: dict[str, Any], **_kwargs) -> str:
    repo = Path(str(args.get("repo") or "")).expanduser()
    if not str(repo):
        return tool_error("repo is required")
    try:
        wiki_root = _wiki_root(args)
        source_root = _source_root(args)
    except ValueError as exc:
        return tool_error(str(exc))
    if not repo.is_absolute():
        repo = source_root / repo
    repo = repo.resolve()
    if not _is_under(repo, source_root):
        return tool_error(f"repo must be under {source_root}: {repo}")
    if not repo.exists():
        return tool_error(f"repo does not exist: {repo}")

    command_args = [
        "repo",
        "add",
        "--repo",
        str(repo),
        "--wiki-root",
        str(wiki_root),
        "--source-root",
        str(source_root),
    ]
    for field, option in (
        ("repo_key", "--repo-key"),
        ("wiki_path", "--wiki-path"),
        ("tracked_branch", "--tracked-branch"),
        ("schedule", "--schedule"),
        ("question", "--question"),
    ):
        value = str(args.get(field) or "").strip()
        if value:
            command_args.extend([option, value])
    if bool(args.get("no_build", False)):
        command_args.append("--no-build")

    try:
        result = _run_forge(args, command_args, timeout=int(args.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS))
    except subprocess.TimeoutExpired:
        return tool_error("llm-wiki forge repo add timed out", next_action="inspect_partial_onboarding_outputs")
    except Exception as exc:
        return tool_error(str(exc), next_action="verify_llm_wiki_forge_install")

    return tool_result(
        {
            "next_action": "validate_or_report",
            "repo": str(repo),
            "exit_code": result["exit_code"],
            "stdout": result["stdout"][-12000:],
            "stderr": result["stderr"][-4000:],
            "command": result["command"],
        }
    )


LLM_WIKI_FORGE_SYNC_SCHEMA = {
    "name": "llm_wiki_forge_sync",
    "description": "Run Forge-owned LLM Wiki repo sync for one registered repo_key. Mutating maintenance tool.",
    "parameters": {
        "type": "object",
        "properties": {
            "repo_key": {"type": "string", "description": "Repo key from Wiki/_meta/repo_sync/repos.json."},
            "wiki_root": {"type": "string", "description": "LLM Wiki root for this run."},
            "source_root": {"type": "string", "description": "Source root that contains registered repos."},
            "python": {"type": "string", "description": "Optional Python interpreter for llm_wiki_forge."},
            "accept_baseline": {"type": "boolean", "default": True},
            "skip_fetch": {"type": "boolean", "default": False},
            "dry_run": {"type": "boolean", "default": False},
            "timeout_seconds": {"type": "integer", "default": DEFAULT_TIMEOUT_SECONDS},
        },
        "required": ["repo_key", "wiki_root", "source_root"],
    },
}


LLM_WIKI_FORGE_REPO_ADD_SCHEMA = {
    "name": "llm_wiki_forge_repo_add",
    "description": "Add a user-provided source repo to a user-provided LLM Wiki via llm-wiki-forge repo add. Mutating maintenance tool.",
    "parameters": {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "Repo path or folder name under source_root."},
            "wiki_root": {"type": "string", "description": "LLM Wiki root for this run."},
            "source_root": {"type": "string", "description": "Source root that contains the repo."},
            "python": {"type": "string", "description": "Optional Python interpreter for llm_wiki_forge."},
            "repo_key": {"type": "string"},
            "wiki_path": {"type": "string"},
            "tracked_branch": {"type": "string"},
            "schedule": {"type": "string"},
            "question": {"type": "string"},
            "no_build": {"type": "boolean", "default": False},
            "timeout_seconds": {"type": "integer", "default": DEFAULT_TIMEOUT_SECONDS},
        },
        "required": ["repo", "wiki_root", "source_root"],
    },
}


registry.register(
    name="llm_wiki_forge_sync",
    toolset="llm-wiki",
    schema=LLM_WIKI_FORGE_SYNC_SCHEMA,
    handler=llm_wiki_forge_sync_tool,
    check_fn=_forge_available,
    description=LLM_WIKI_FORGE_SYNC_SCHEMA["description"],
    emoji="🛠️",
)

registry.register(
    name="llm_wiki_forge_repo_add",
    toolset="llm-wiki",
    schema=LLM_WIKI_FORGE_REPO_ADD_SCHEMA,
    handler=llm_wiki_forge_repo_add_tool,
    check_fn=_forge_available,
    description=LLM_WIKI_FORGE_REPO_ADD_SCHEMA["description"],
    emoji="🛠️",
)
