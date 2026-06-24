from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

from llm_wiki_forge.repo_sync import DEFAULT_SOURCE_ROOT, DEFAULT_WIKI_ROOT, read_json, require_under, write_json
from llm_wiki_forge.runtime import packaged_module_available, run_packaged_module
from llm_wiki_forge.workflows import (
    refresh_wiki_artifacts,
    run_code_query,
    run_code_source_search,
    update_repo_and_refresh_wiki,
    workflow_summary,
)


def info(message: str) -> None:
    print(message, flush=True)


def run(command: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    info("+ " + " ".join(f'"{part}"' if " " in part else part for part in command))
    return subprocess.run(command, cwd=str(cwd) if cwd else None, check=check)


def command_works(command: list[str]) -> bool:
    try:
        result = subprocess.run(command + ["--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.returncode == 0
    except OSError:
        return False


def venv_python(wiki_root: Path) -> Path:
    if os.name == "nt":
        return wiki_root / ".venv" / "Scripts" / "python.exe"
    return wiki_root / ".venv" / "bin" / "python"


def first_system_python() -> list[str] | None:
    candidates: list[list[str]] = []
    if sys.executable:
        candidates.append([sys.executable])
    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            candidates.append([found])
    py_launcher = shutil.which("py")
    if py_launcher:
        candidates.append([py_launcher, "-3"])

    seen: set[tuple[str, ...]] = set()
    for candidate in candidates:
        key = tuple(candidate)
        if key in seen:
            continue
        seen.add(key)
        if command_works(candidate):
            return candidate
    return None


def ensure_python(wiki_root: Path, install_requirements: bool = False) -> Path:
    wiki_root.mkdir(parents=True, exist_ok=True)
    py = venv_python(wiki_root)
    if not py.exists():
        system_python = first_system_python()
        if not system_python:
            raise SystemExit("Python 3.11+ was not found. Install Python or pass a prepared wiki root with .venv.")

        run(system_python + ["-m", "venv", str(wiki_root / ".venv")])
        if not py.exists():
            raise SystemExit(f"Failed to create venv Python at {py}")

    requirements = wiki_root / "requirements.txt"
    if install_requirements and requirements.exists():
        run([str(py), "-m", "pip", "install", "-r", str(requirements)])
    return py


def infer_project_name(repo_path: Path, explicit: str | None) -> str:
    return explicit or repo_path.name


def infer_wiki_root(repo_path: Path, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (repo_path.parent / f"{repo_path.name}-llm-wiki").resolve()


def has_infrastructure(wiki_root: Path) -> bool:
    return (
        (wiki_root / "wiki.scope.json").exists()
        and (wiki_root / "Wiki").is_dir()
    )


def bootstrap_script_path() -> Path:
    return Path(str(resources.files("llm_wiki_forge.resources").joinpath("bootstrap_llm_wiki.py")))


def print_context(repo_path: Path | None, wiki_root: Path, python_path: Path, project_name: str | None, mode: str) -> None:
    info("LLM Wiki Forge context")
    if repo_path:
        info(f"Repo path: {repo_path}")
    info(f"Wiki root: {wiki_root}")
    info(f"Python: {python_path}")
    if project_name:
        info(f"Project name: {project_name}")
    info(f"Mode: {mode}")


def run_bootstrap(args: argparse.Namespace) -> Path:
    repo_path = Path(args.repo).expanduser().resolve() if args.repo else None
    if repo_path and not repo_path.exists():
        raise SystemExit(f"Repo path does not exist: {repo_path}")

    wiki_root = infer_wiki_root(repo_path, args.wiki_root) if repo_path else Path(args.wiki_root).expanduser().resolve()
    project_name = infer_project_name(repo_path, args.project_name) if repo_path else args.project_name
    python_path = ensure_python(wiki_root, install_requirements=args.install_requirements)
    print_context(repo_path, wiki_root, python_path, project_name, "bootstrap")

    command = [
        str(python_path),
        str(bootstrap_script_path()),
        "--wiki-root",
        str(wiki_root),
        "--python-command",
        str(python_path),
    ]
    if repo_path:
        command += ["--repo-path", str(repo_path)]
    if project_name:
        command += ["--project-name", project_name]
    run(command)
    if args.install_requirements:
        ensure_python(wiki_root, install_requirements=True)
    return wiki_root


def run_wiki_command(wiki_root: Path, python_path: Path, module: str, *args: str, required: bool = True) -> int:
    if packaged_module_available(module):
        info("+ " + " ".join([str(python_path), "-m", module, *args]))
        result = run_packaged_module(python_path, module, list(args), cwd=wiki_root)
    else:
        result = run([str(python_path), "-m", module, *args], cwd=wiki_root, check=False)
    if required and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.returncode


def run_onboarding_steps(
    wiki_root: Path,
    python_path: Path,
    project_name: str,
    smoke_question: str | None = None,
) -> None:
    refresh_wiki_artifacts(
        wiki_root=wiki_root,
        python_path=python_path,
        repo=project_name,
        question=smoke_question,
    )


def run_community_build(wiki_root: Path, python_path: Path, top_per_module: int) -> None:
    run_wiki_command(
        wiki_root,
        python_path,
        "scripts.query_runtime.community_builder",
        "--wiki-root",
        str(wiki_root),
        "--top-per-module",
        str(top_per_module),
    )


def is_git_repo(repo_path: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "--is-inside-work-tree"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def initialize_sync_state(wiki_root: Path, python_path: Path, repo_path: Path, project_name: str) -> None:
    if not is_git_repo(repo_path):
        info("Repo sync state: skipped (source repo is not git-backed)")
        return
    run_wiki_command(
        wiki_root,
        python_path,
        "scripts.repo_sync.diff_wiki",
        "--wiki-root",
        str(wiki_root),
        "--repo-root",
        str(repo_path),
        "--state",
        f"Wiki/_meta/repo_sync/{project_name}.json",
        "--baseline",
        "HEAD",
        "--target-ref",
        "HEAD",
        "--accept-baseline",
    )


def _git_stdout(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _scope_path(repo_path: Path, source_root: Path) -> str:
    try:
        relative = repo_path.resolve().relative_to(source_root.resolve()).as_posix()
        return "${domainRoot}/" + relative
    except ValueError:
        return str(repo_path)


def _upsert_scope_repo(wiki_root: Path, repo_key: str, repo_path: Path, wiki_path: str, source_root: Path) -> None:
    scope_path = wiki_root / "wiki.scope.json"
    if not scope_path.exists():
        raise SystemExit(f"wiki.scope.json not found: {scope_path}")
    scope = read_json(scope_path)
    if not isinstance(scope, dict):
        raise SystemExit(f"wiki.scope.json must be a JSON object: {scope_path}")
    repos = scope.setdefault("repos", [])
    if not isinstance(repos, list):
        raise SystemExit("wiki.scope.json field repos must be a list")

    actual_root = _scope_path(repo_path, source_root)
    entry = {
        "logicalName": repo_key,
        "actualRoot": actual_root,
        "include": True,
        "reason": "Single-module project onboarded by llm-wiki-forge.",
        "targets": [
            {
                "logicalName": wiki_path or repo_key,
                "actualPath": actual_root,
                "type": "project-root",
                "include": True,
                "reason": "Initial whole-repo module.",
            }
        ],
    }

    for index, existing in enumerate(repos):
        if not isinstance(existing, dict):
            continue
        if existing.get("logicalName") == repo_key or existing.get("actualRoot") == actual_root:
            repos[index] = {**existing, **entry}
            write_json(scope_path, scope)
            return
    repos.append(entry)
    write_json(scope_path, scope)


def _upsert_repo_sync_config(
    wiki_root: Path,
    repo_key: str,
    repo_path: Path,
    tracked_branch: str,
    schedule: str | None,
) -> None:
    config_path = wiki_root / "Wiki" / "_meta" / "repo_sync" / "repos.json"
    config = read_json(config_path) if config_path.exists() else {"version": 1, "defaultCronWorkdir": str(wiki_root), "repos": []}
    if not isinstance(config, dict):
        raise SystemExit(f"Repo sync config must be a JSON object: {config_path}")
    repos = config.setdefault("repos", [])
    if not isinstance(repos, list):
        raise SystemExit("repo sync config field repos must be a list")

    entry = {
        "repoKey": repo_key,
        "displayName": repo_key,
        "repoRoot": str(repo_path),
        "gitRemote": "origin",
        "trackedBranch": tracked_branch,
        "stateFile": f"Wiki/_meta/repo_sync/{repo_key}.json",
        "allowDirtyPathGlobs": [
            "graphify-out",
            "graphify-out/*",
            "*/graphify-out",
            "*/graphify-out/*",
        ],
        "cron": {
            "name": f"LLM Wiki Sync - {repo_key}",
            "deliver": "local",
            "skills": ["llm-wiki-master-sync"],
        },
    }
    if schedule:
        entry["schedule"] = schedule

    for index, existing in enumerate(repos):
        if isinstance(existing, dict) and existing.get("repoKey") == repo_key:
            merged = {**existing, **entry}
            if schedule is None and "schedule" in existing:
                merged["schedule"] = existing["schedule"]
            repos[index] = merged
            write_json(config_path, config)
            return
    repos.append(entry)
    write_json(config_path, config)


def command_repo_add(args: argparse.Namespace) -> None:
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    source_root = Path(args.source_root).expanduser().resolve()
    repo_path = Path(args.repo).expanduser().resolve()
    repo_key = args.repo_key or repo_path.name
    wiki_path = args.wiki_path or repo_key

    require_under(wiki_root, DEFAULT_WIKI_ROOT.parent, "wiki_root")
    require_under(repo_path, source_root, "repo")
    if not repo_path.exists():
        raise SystemExit(f"Repo path does not exist: {repo_path}")

    tracked_branch = args.tracked_branch or _git_stdout(repo_path, "rev-parse", "--abbrev-ref", "HEAD") or "main"
    python_path = ensure_python(wiki_root, install_requirements=args.install_requirements)
    print_context(repo_path, wiki_root, python_path, repo_key, "repo add")

    _upsert_scope_repo(wiki_root, repo_key, repo_path, wiki_path, source_root)
    _upsert_repo_sync_config(wiki_root, repo_key, repo_path, tracked_branch, args.schedule)
    info(f"Updated scope and repo sync registry for {repo_key}.")

    if args.no_build:
        info("Build skipped by --no-build.")
    else:
        run_onboarding_steps(wiki_root, python_path, repo_key, args.question)
        command_validate(argparse.Namespace(wiki_root=str(wiki_root), repo=repo_key, question=args.question, install_requirements=False))

    initialize_sync_state(wiki_root, python_path, repo_path, repo_key)
    info("Verdict: PASS")


def command_build(args: argparse.Namespace) -> None:
    repo_path = Path(args.repo).expanduser().resolve()
    if not repo_path.exists():
        raise SystemExit(f"Repo path does not exist: {repo_path}")
    wiki_root = infer_wiki_root(repo_path, args.wiki_root)
    project_name = infer_project_name(repo_path, args.project_name)
    mode = "onboarding-only" if has_infrastructure(wiki_root) else "bootstrap+onboarding"
    python_path = ensure_python(wiki_root, install_requirements=args.install_requirements)
    print_context(repo_path, wiki_root, python_path, project_name, mode)

    if mode == "bootstrap+onboarding":
        bootstrap_args = argparse.Namespace(
            repo=str(repo_path),
            wiki_root=str(wiki_root),
            project_name=project_name,
            install_requirements=args.install_requirements,
        )
        run_bootstrap(bootstrap_args)

    run_onboarding_steps(wiki_root, python_path, project_name, args.question)
    command_validate(argparse.Namespace(wiki_root=str(wiki_root), repo=project_name, question=args.question, install_requirements=False))
    initialize_sync_state(wiki_root, python_path, repo_path, project_name)
    info("Verdict: PASS")


def command_validate(args: argparse.Namespace) -> None:
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    python_path = ensure_python(wiki_root, install_requirements=args.install_requirements)
    project_name = args.repo
    print_context(None, wiki_root, python_path, project_name, "validate")

    required = [
        wiki_root / "wiki.scope.json",
        wiki_root / "Wiki" / "_data" / "modules",
        wiki_root / "Wiki" / "01_Modules",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Missing required wiki artifacts:\n" + "\n".join(missing))

    if project_name:
        modules_dir = wiki_root / "Wiki" / "_data" / "modules"
        matching_modules = []
        for module_file in modules_dir.glob("*.json"):
            try:
                module = json.loads(module_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if module.get("logicalName") == project_name or module.get("sourcePath") == project_name:
                matching_modules.append(module_file)
        if not matching_modules:
            raise SystemExit(f"Missing module artifact for {project_name} under {modules_dir}")

        question = args.question or f"What is the main responsibility of {project_name}?"
        code = run_wiki_command(
            wiki_root,
            python_path,
            "scripts.query_runtime.graph_runtime",
            "--wiki-root",
            str(wiki_root),
            "--question",
            question,
            "--top",
            "5",
            "--extract",
            "--extract-limit",
            "4",
            required=False,
        )
        if code != 0:
            raise SystemExit(f"Query smoke failed for {project_name}; see Wiki/_data/query_runs for partial evidence.")
    info("Verdict: PASS")


def command_backfill(args: argparse.Namespace) -> None:
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    python_path = ensure_python(wiki_root, install_requirements=args.install_requirements)
    print_context(None, wiki_root, python_path, args.repo, "refresh")
    steps = refresh_wiki_artifacts(
        wiki_root=wiki_root,
        python_path=python_path,
        repo=args.repo,
        question=args.question,
        community_top_per_module=getattr(args, "top_per_module", 10),
    )
    if getattr(args, "json", False):
        print(json.dumps(workflow_summary(steps), ensure_ascii=False, indent=2))
    info("Verdict: PASS")


def command_query(args: argparse.Namespace) -> None:
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    python_path = ensure_python(wiki_root, install_requirements=True) if args.install_requirements else Path(sys.executable)
    raise SystemExit(
        run_code_query(
            wiki_root=wiki_root,
            python_path=python_path,
            question=args.question,
            top=args.top,
            extract_limit=args.extract_limit,
            json_output=args.json,
            detail=args.detail,
            reuse_recent=args.reuse_recent,
            reuse_days=args.reuse_days,
            max_shards=args.max_shards,
        )
    )


def command_graph(args: argparse.Namespace) -> None:
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    python_path = ensure_python(wiki_root, install_requirements=True) if args.install_requirements else Path(sys.executable)
    runtime_args = [
        "--wiki-root",
        str(wiki_root),
        "--question",
        args.question,
        "--top",
        str(args.top),
        "--extract-limit",
        str(args.extract_limit),
    ]
    if args.extract:
        runtime_args.append("--extract")
    run_wiki_command(wiki_root, python_path, "scripts.query_runtime.graph_runtime", *runtime_args)


def command_source_search(args: argparse.Namespace) -> None:
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    python_path = ensure_python(wiki_root, install_requirements=True) if args.install_requirements else Path(sys.executable)
    raise SystemExit(
        run_code_source_search(
            wiki_root=wiki_root,
            python_path=python_path,
            patterns=args.pattern,
            roots=args.root or [],
            limit=args.limit,
            regex=args.regex,
            include_sql=args.include_sql,
            json_output=args.json,
            detail=args.detail,
        )
    )


def command_eval(args: argparse.Namespace) -> None:
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    python_path = ensure_python(wiki_root, install_requirements=True) if args.install_requirements else Path(sys.executable)
    run_wiki_command(
        wiki_root,
        python_path,
        "scripts.query_runtime.eval_queries",
        "--wiki-root",
        str(wiki_root),
        "--runtime",
        args.runtime,
    )


def command_community_build(args: argparse.Namespace) -> None:
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    python_path = ensure_python(wiki_root, install_requirements=True) if args.install_requirements else Path(sys.executable)
    run_community_build(wiki_root, python_path, args.top_per_module)


def command_sync(args: argparse.Namespace) -> None:
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    python_path = ensure_python(wiki_root, install_requirements=True) if args.install_requirements else Path(sys.executable)
    if args.repo_key:
        exit_code = update_repo_and_refresh_wiki(
            wiki_root=wiki_root,
            repo_key=args.repo_key,
            python_path=python_path,
            config_file=args.config_file,
            source_root=Path(args.source_root).expanduser().resolve(),
            skip_fetch=args.skip_fetch,
            dry_run=args.dry_run,
            accept_baseline=args.accept_baseline,
        )
        raise SystemExit(exit_code)

    if not args.repo:
        raise SystemExit("sync requires either --repo-key or --repo")

    repo_path = Path(args.repo).expanduser().resolve()
    project_name = infer_project_name(repo_path, args.project_name)
    print_context(repo_path, wiki_root, python_path, project_name, "sync")
    command = [
        "--wiki-root",
        str(wiki_root),
        "--repo-root",
        str(repo_path),
        "--state",
        f"Wiki/_meta/repo_sync/{project_name}.json",
        "--target-ref",
        args.target_ref,
    ]
    if args.accept_baseline:
        command.append("--accept-baseline")
    run_wiki_command(wiki_root, python_path, "scripts.repo_sync.diff_wiki", *command)


def command_update(args: argparse.Namespace) -> None:
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    python_path = ensure_python(wiki_root, install_requirements=args.install_requirements)
    print_context(None, wiki_root, python_path, args.repo_key, "update")
    raise SystemExit(
        update_repo_and_refresh_wiki(
            wiki_root=wiki_root,
            repo_key=args.repo_key,
            python_path=python_path,
            config_file=args.config_file,
            source_root=Path(args.source_root).expanduser().resolve(),
            skip_fetch=args.skip_fetch,
            dry_run=args.dry_run,
            accept_baseline=args.accept_baseline,
        )
    )


def command_install_hermes(args: argparse.Namespace) -> None:
    hermes_root = Path(args.hermes_root).expanduser().resolve()
    integration = resources.files("llm_wiki_forge.resources").joinpath("integrations/hermes")
    sections = ["tools", "skills", "tests"]
    if not args.no_hook:
        sections.append("hooks")

    with resources.as_file(integration) as integration_root:
        manifest_path = integration_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        install = manifest.get("install") or {}
        copied = 0
        for section in sections:
            entries = install.get(section) or []
            for entry in entries:
                source = integration_root / entry["source"]
                target = hermes_root / entry["target"]
                if not source.is_file():
                    raise SystemExit(f"Missing Hermes integration source: {source}")
                info(f"{'Would copy' if args.dry_run else 'Copy'} {source} -> {target}")
                if not args.dry_run:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                copied += 1

    info(f"Hermes integration {'dry run' if args.dry_run else 'installed'}: {copied} file(s)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-wiki", description="LLM Wiki Forge CLI")
    parser.add_argument("--version", action="version", version="llm-wiki-forge 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="Bootstrap if needed, build one module, and validate.")
    build.add_argument("--repo", required=True, help="Source repo path.")
    build.add_argument("--wiki-root", help="LLM Wiki root. Defaults to <repo_parent>/<repo_name>-llm-wiki.")
    build.add_argument("--project-name", help="Module name. Defaults to repo folder name.")
    build.add_argument("--question", help="Smoke question.")
    build.add_argument("--install-requirements", action="store_true", help="Install requirements.txt into the wiki venv when present.")
    build.set_defaults(func=command_build)

    bootstrap = sub.add_parser("bootstrap", help="Create a first-run LLM Wiki root.")
    bootstrap.add_argument("--repo", help="Optional source repo path.")
    bootstrap.add_argument("--wiki-root", required=True, help="LLM Wiki root to create.")
    bootstrap.add_argument("--project-name", help="Module name. Defaults to repo folder name.")
    bootstrap.add_argument("--install-requirements", action="store_true")
    bootstrap.set_defaults(func=lambda args: run_bootstrap(args))

    validate = sub.add_parser("validate", help="Run a focused validation smoke.")
    validate.add_argument("--wiki-root", required=True)
    validate.add_argument("--repo", help="Repo/module name for focused smoke.")
    validate.add_argument("--question", help="Smoke question.")
    validate.add_argument("--install-requirements", action="store_true")
    validate.set_defaults(func=command_validate)

    backfill = sub.add_parser("backfill", help="Refresh module/community/query artifacts for one existing repo.")
    backfill.add_argument("--wiki-root", required=True)
    backfill.add_argument("--repo", required=True)
    backfill.add_argument("--question", help="Smoke question.")
    backfill.add_argument("--top-per-module", type=int, default=10)
    backfill.add_argument("--json", action="store_true", help="Print a compact workflow summary.")
    backfill.add_argument("--install-requirements", action="store_true")
    backfill.set_defaults(func=command_backfill)

    refresh = sub.add_parser("refresh", help="Forge-owned alias for refreshing wiki artifacts for one repo.")
    refresh.add_argument("--wiki-root", required=True)
    refresh.add_argument("--repo", required=True)
    refresh.add_argument("--question", help="Smoke question.")
    refresh.add_argument("--top-per-module", type=int, default=10)
    refresh.add_argument("--json", action="store_true", help="Print a compact workflow summary.")
    refresh.add_argument("--install-requirements", action="store_true")
    refresh.set_defaults(func=command_backfill)

    update = sub.add_parser("update", help="Update a registered repo and refresh wiki artifacts through Forge.")
    update.add_argument("--wiki-root", required=True)
    update.add_argument("--repo-key", required=True, help="Repo key from Wiki/_meta/repo_sync/repos.json.")
    update.add_argument("--config-file", default="Wiki/_meta/repo_sync/repos.json")
    update.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    update.add_argument("--accept-baseline", action="store_true", default=True)
    update.add_argument("--no-accept-baseline", dest="accept_baseline", action="store_false")
    update.add_argument("--skip-fetch", action="store_true")
    update.add_argument("--dry-run", action="store_true")
    update.add_argument("--install-requirements", action="store_true")
    update.set_defaults(func=command_update)

    query = sub.add_parser("query", help="Run the packaged query orchestrator.")
    query.add_argument("--wiki-root", required=True)
    query.add_argument("--question", required=True)
    query.add_argument("--top", type=int, default=5)
    query.add_argument("--extract-limit", type=int, default=4)
    query.add_argument("--json", action="store_true")
    query.add_argument("--detail", choices=["compact", "full"], default="compact")
    query.add_argument("--reuse-recent", dest="reuse_recent", action="store_true", default=True)
    query.add_argument("--no-reuse-recent", dest="reuse_recent", action="store_false")
    query.add_argument("--reuse-days", type=int, default=7)
    query.add_argument("--max-shards", type=int, default=3)
    query.add_argument("--install-requirements", action="store_true")
    query.set_defaults(func=command_query)

    graph = sub.add_parser("graph", help="Run the packaged graph query runtime.")
    graph.add_argument("--wiki-root", required=True)
    graph.add_argument("--question", required=True)
    graph.add_argument("--top", type=int, default=5)
    graph.add_argument("--extract", action="store_true")
    graph.add_argument("--extract-limit", type=int, default=4)
    graph.add_argument("--install-requirements", action="store_true")
    graph.set_defaults(func=command_graph)

    source_search = sub.add_parser("source-search", help="Run packaged fixed-string source search.")
    source_search.add_argument("--wiki-root", required=True)
    source_search.add_argument("--pattern", action="append", required=True)
    source_search.add_argument("--root", action="append", default=[])
    source_search.add_argument("--limit", type=int, default=20)
    source_search.add_argument("--regex", action="store_true")
    source_search.add_argument("--include-sql", action="store_true")
    source_search.add_argument("--json", action="store_true")
    source_search.add_argument("--detail", choices=["compact", "full"], default="compact")
    source_search.add_argument("--install-requirements", action="store_true")
    source_search.set_defaults(func=command_source_search)

    code = sub.add_parser("code", help="Forge-owned code evidence query commands.")
    code_sub = code.add_subparsers(dest="code_command", required=True)
    code_query = code_sub.add_parser("query", help="Run the code query orchestrator.")
    code_query.add_argument("--wiki-root", required=True)
    code_query.add_argument("--question", required=True)
    code_query.add_argument("--top", type=int, default=5)
    code_query.add_argument("--extract-limit", type=int, default=4)
    code_query.add_argument("--json", action="store_true")
    code_query.add_argument("--detail", choices=["compact", "full"], default="compact")
    code_query.add_argument("--reuse-recent", dest="reuse_recent", action="store_true", default=True)
    code_query.add_argument("--no-reuse-recent", dest="reuse_recent", action="store_false")
    code_query.add_argument("--reuse-days", type=int, default=7)
    code_query.add_argument("--max-shards", type=int, default=3)
    code_query.add_argument("--install-requirements", action="store_true")
    code_query.set_defaults(func=command_query)

    code_source_search = code_sub.add_parser("source-search", help="Run deterministic source search.")
    code_source_search.add_argument("--wiki-root", required=True)
    code_source_search.add_argument("--pattern", action="append", required=True)
    code_source_search.add_argument("--root", action="append", default=[])
    code_source_search.add_argument("--limit", type=int, default=20)
    code_source_search.add_argument("--regex", action="store_true")
    code_source_search.add_argument("--include-sql", action="store_true")
    code_source_search.add_argument("--json", action="store_true")
    code_source_search.add_argument("--detail", choices=["compact", "full"], default="compact")
    code_source_search.add_argument("--install-requirements", action="store_true")
    code_source_search.set_defaults(func=command_source_search)

    eval_cmd = sub.add_parser("eval", help="Run packaged query runtime evaluation.")
    eval_cmd.add_argument("--wiki-root", required=True)
    eval_cmd.add_argument("--runtime", choices=["graph", "classic"], required=True)
    eval_cmd.add_argument("--install-requirements", action="store_true")
    eval_cmd.set_defaults(func=command_eval)

    community = sub.add_parser("community", help="Manage packaged community artifacts.")
    community_sub = community.add_subparsers(dest="community_command", required=True)
    community_build = community_sub.add_parser("build", help="Build packaged community navigation.")
    community_build.add_argument("--wiki-root", required=True)
    community_build.add_argument("--top-per-module", type=int, default=10)
    community_build.add_argument("--install-requirements", action="store_true")
    community_build.set_defaults(func=command_community_build)

    sync = sub.add_parser("sync", help="Create or update repo sync diff state.")
    sync.add_argument("--repo")
    sync.add_argument("--repo-key", help="Repo key from Wiki/_meta/repo_sync/repos.json.")
    sync.add_argument("--wiki-root", required=True)
    sync.add_argument("--config-file", default="Wiki/_meta/repo_sync/repos.json")
    sync.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    sync.add_argument("--project-name")
    sync.add_argument("--target-ref", default="HEAD")
    sync.add_argument("--accept-baseline", action="store_true")
    sync.add_argument("--skip-fetch", action="store_true")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--install-requirements", action="store_true")
    sync.set_defaults(func=command_sync)

    repo = sub.add_parser("repo", help="Manage source repos in a multi-repo wiki registry.")
    repo_sub = repo.add_subparsers(dest="repo_command", required=True)
    repo_add = repo_sub.add_parser("add", help="Add or update one DispatchRawdata repo in wiki.scope.json and repo sync registry.")
    repo_add.add_argument("--repo", required=True, help="Source repo path under DispatchRawdata.")
    repo_add.add_argument("--wiki-root", required=True)
    repo_add.add_argument("--repo-key", help="Stable repo key. Defaults to repo folder name.")
    repo_add.add_argument("--wiki-path", help="Target module/wiki logical path. Defaults to repo key.")
    repo_add.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    repo_add.add_argument("--tracked-branch", help="Tracked branch. Defaults to the current git branch, then main.")
    repo_add.add_argument("--schedule", help="Optional cron expression for future sync registration.")
    repo_add.add_argument("--question", help="Smoke question.")
    repo_add.add_argument("--no-build", action="store_true", help="Only update registry/scope and sync state.")
    repo_add.add_argument("--install-requirements", action="store_true")
    repo_add.set_defaults(func=command_repo_add)

    integrations = sub.add_parser("integrations", help="Manage Forge-owned runtime integration packs.")
    integrations_sub = integrations.add_subparsers(dest="integrations_command", required=True)
    install_hermes = integrations_sub.add_parser("install-hermes", help="Install the Forge-owned Hermes integration pack.")
    install_hermes.add_argument("--hermes-root", default="/home/tedhsu/.hermes")
    install_hermes.add_argument("--dry-run", action="store_true")
    install_hermes.add_argument("--no-hook", action="store_true", help="Do not install the Slack read-only guard copy.")
    install_hermes.set_defaults(func=command_install_hermes)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
