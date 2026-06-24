from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_wiki_forge.repo_sync import DEFAULT_SOURCE_ROOT, invoke_repo_sync
from llm_wiki_forge.runtime import packaged_module_available, run_packaged_module


@dataclass
class ModuleStep:
    name: str
    module: str
    args: list[str]
    exit_code: int


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
    config_file: str = "Wiki/_meta/repo_sync/repos.json",
    source_root: Path = DEFAULT_SOURCE_ROOT,
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
) -> int:
    """Run the Forge-owned code query orchestrator."""

    args = [
        "--wiki-root",
        str(wiki_root),
        "--question",
        question,
        "--top",
        str(top),
        "--extract-limit",
        str(extract_limit),
    ]
    if json_output:
        args.append("--json")
    return run_runtime_module(
        wiki_root=wiki_root,
        python_path=python_path,
        module="scripts.query_runtime.query_orchestrator",
        args=args,
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
) -> int:
    """Run deterministic Forge-owned source search for exact code evidence."""

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
