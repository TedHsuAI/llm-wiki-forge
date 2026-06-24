#!/usr/bin/env python3
"""Hermes maintenance tools for Forge-owned LLM Wiki build/sync flows."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from tools.registry import registry, tool_error, tool_result


DEFAULT_WIKI_ROOT = Path("/home/tedhsu/.hermes/data/llm-wiki")
DEFAULT_SOURCE_ROOT = Path("/home/tedhsu/DispatchRawdata")
DEFAULT_PYTHON = "/home/tedhsu/.hermes/hermes-agent/venv/bin/python"
DEFAULT_TIMEOUT_SECONDS = 900


def _python_bin() -> str:
    return os.environ.get("HERMES_LLM_WIKI_FORGE_PYTHON") or os.environ.get("HERMES_LLM_WIKI_PYTHON") or DEFAULT_PYTHON


def _wiki_root() -> Path:
    return Path(os.environ.get("HERMES_LLM_WIKI_ROOT", str(DEFAULT_WIKI_ROOT))).expanduser()


def _source_root() -> Path:
    return Path(os.environ.get("HERMES_LLM_WIKI_SOURCE_ROOT", str(DEFAULT_SOURCE_ROOT))).expanduser()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except Exception:
        return False


def _forge_available() -> bool:
    root = _wiki_root()
    return root.is_dir() and (root / "wiki.scope.json").is_file()


def _run_forge(args: list[str], timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    command = [_python_bin(), "-m", "llm_wiki_forge", *args]
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

    command_args = [
        "update",
        "--wiki-root",
        str(_wiki_root()),
        "--source-root",
        str(_source_root()),
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
        result = _run_forge(command_args, timeout=int(args.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS))
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
    if not repo.is_absolute():
        repo = _source_root() / repo
    repo = repo.resolve()
    if not _is_under(repo, _source_root()):
        return tool_error(f"repo must be under {_source_root()}: {repo}")
    if not repo.exists():
        return tool_error(f"repo does not exist: {repo}")

    command_args = [
        "repo",
        "add",
        "--repo",
        str(repo),
        "--wiki-root",
        str(_wiki_root()),
        "--source-root",
        str(_source_root()),
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
        result = _run_forge(command_args, timeout=int(args.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS))
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
            "accept_baseline": {"type": "boolean", "default": True},
            "skip_fetch": {"type": "boolean", "default": False},
            "dry_run": {"type": "boolean", "default": False},
            "timeout_seconds": {"type": "integer", "default": DEFAULT_TIMEOUT_SECONDS},
        },
        "required": ["repo_key"],
    },
}


LLM_WIKI_FORGE_REPO_ADD_SCHEMA = {
    "name": "llm_wiki_forge_repo_add",
    "description": "Add a DispatchRawdata repo to the local LLM Wiki via llm-wiki-forge repo add. Mutating maintenance tool.",
    "parameters": {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "Repo path or folder name under DispatchRawdata."},
            "repo_key": {"type": "string"},
            "wiki_path": {"type": "string"},
            "tracked_branch": {"type": "string"},
            "schedule": {"type": "string"},
            "question": {"type": "string"},
            "no_build": {"type": "boolean", "default": False},
            "timeout_seconds": {"type": "integer", "default": DEFAULT_TIMEOUT_SECONDS},
        },
        "required": ["repo"],
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
