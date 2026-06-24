from __future__ import annotations

import subprocess
import os
import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_wiki_forge.query_adapter import llm_wiki_query_tool, llm_wiki_source_search_tool
from llm_wiki_forge.repo_sync import invoke_repo_sync
from llm_wiki_forge.runtime import packaged_module_available, run_packaged_module


@dataclass
class ModuleStep:
    name: str
    module: str
    args: list[str]
    exit_code: int


@contextmanager
def _query_env(wiki_root: Path, python_path: Path):
    keys = {
        "HERMES_LLM_WIKI_ROOT": str(wiki_root),
        "HERMES_LLM_WIKI_PYTHON": str(python_path),
    }
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(keys)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_runtime_module(
    *,
    wiki_root: Path,
    python_path: Path,
    module: str,
    args: list[str],
    capture_output: bool = False,
) -> subprocess.CompletedProcess:
    """Run a Forge-owned runtime module from the package when available."""

    if packaged_module_available(module):
        return run_packaged_module(
            python_path,
            module,
            args,
            cwd=wiki_root,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
        )
    return subprocess.run(
        [str(python_path), "-m", module, *args],
        cwd=str(wiki_root),
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=True,
        check=False,
    )


def refresh_wiki_artifacts(
    *,
    wiki_root: Path,
    python_path: Path,
    repo: str,
    question: str | None = None,
    community_top_per_module: int = 10,
) -> list[ModuleStep]:
    """Refresh generated wiki artifacts for an existing repo/module.

    This is the Forge-owned equivalent of the old ad hoc "refresh wiki"
    sequence: update inventory, rebuild module pages, rebuild community
    navigation, then run one focused smoke query.
    """

    steps: list[ModuleStep] = []
    commands = [
        (
            "refresh-scope-inventory",
            "scripts.update_wiki",
            ["--wiki-root", str(wiki_root)],
        ),
        (
            "rebuild-modules",
            "scripts.generate_module_wiki",
            ["--wiki-root", str(wiki_root)],
        ),
        (
            "rebuild-communities",
            "scripts.query_runtime.community_builder",
            ["--wiki-root", str(wiki_root), "--top-per-module", str(community_top_per_module)],
        ),
        (
            "smoke-query",
            "scripts.query_runtime.graph_runtime",
            [
                "--wiki-root",
                str(wiki_root),
                "--question",
                question or f"What is the main responsibility of {repo}?",
                "--top",
                "5",
                "--extract",
                "--extract-limit",
                "4",
            ],
        ),
    ]
    for name, module, module_args in commands:
        result = run_runtime_module(
            wiki_root=wiki_root,
            python_path=python_path,
            module=module,
            args=module_args,
        )
        step = ModuleStep(name=name, module=module, args=module_args, exit_code=result.returncode)
        steps.append(step)
        if result.returncode != 0:
            raise SystemExit(result.returncode)
    return steps


def update_repo_and_refresh_wiki(
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
    """Update a registered source repo and run the Forge full-sync pipeline."""

    return invoke_repo_sync(
        wiki_root=wiki_root,
        repo_key=repo_key,
        python_path=python_path,
        config_file=config_file,
        source_root=source_root,
        skip_fetch=skip_fetch,
        dry_run=dry_run,
        accept_baseline=accept_baseline,
    )


def run_code_query(
    *,
    wiki_root: Path,
    python_path: Path,
    question: str,
    top: int = 5,
    extract_limit: int = 4,
    json_output: bool = False,
    detail: str = "compact",
    reuse_recent: bool = True,
    reuse_days: int = 7,
    max_shards: int = 3,
) -> int:
    """Run the Forge-owned code query path with Hermes-compatible shaping."""

    if json_output:
        with _query_env(wiki_root, python_path):
            result = llm_wiki_query_tool(
                {
                    "question": question,
                    "top": top,
                    "extract_limit": extract_limit,
                    "detail": detail,
                    "reuse_recent": reuse_recent,
                    "reuse_days": reuse_days,
                    "max_shards": max_shards,
                }
            )
            print(result)
            try:
                payload = json.loads(result)
            except json.JSONDecodeError:
                payload = {}
            if payload.get("error"):
                return 1
        return 0

    return run_runtime_module(
        wiki_root=wiki_root,
        python_path=python_path,
        module="scripts.query_runtime.query_orchestrator",
        args=[
            "--wiki-root",
            str(wiki_root),
            "--question",
            question,
            "--top",
            str(top),
            "--extract-limit",
            str(extract_limit),
        ],
    ).returncode


def run_code_source_search(
    *,
    wiki_root: Path,
    python_path: Path,
    patterns: list[str],
    roots: list[str] | None = None,
    limit: int = 20,
    regex: bool = False,
    include_sql: bool = False,
    json_output: bool = False,
    detail: str = "compact",
) -> int:
    """Run deterministic Forge-owned source search for exact code evidence."""

    if json_output and not regex and not include_sql and len(patterns) == 1:
        with _query_env(wiki_root, python_path):
            result = llm_wiki_source_search_tool(
                {
                    "pattern": patterns[0],
                    "root": (roots or [""])[0] if roots else "",
                    "limit": limit,
                    "detail": detail,
                }
            )
            print(result)
            try:
                payload = json.loads(result)
            except json.JSONDecodeError:
                payload = {}
            if payload.get("error"):
                return 1
        return 0

    args = ["--wiki-root", str(wiki_root), "--limit", str(limit)]
    for pattern in patterns:
        args.extend(["--pattern", pattern])
    for root in roots or []:
        args.extend(["--root", root])
    if regex:
        args.append("--regex")
    if include_sql:
        args.append("--include-sql")
    if json_output:
        args.append("--json")
    return run_runtime_module(
        wiki_root=wiki_root,
        python_path=python_path,
        module="scripts.query_runtime.source_search",
        args=args,
    ).returncode


def workflow_summary(steps: list[ModuleStep]) -> dict[str, Any]:
    return {
        "steps": [
            {
                "name": step.name,
                "module": step.module,
                "exit_code": step.exit_code,
            }
            for step in steps
        ],
        "status": "completed" if all(step.exit_code == 0 for step in steps) else "failed",
    }
