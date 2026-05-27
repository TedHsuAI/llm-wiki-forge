from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path


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
    if py.exists():
        return py

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
        and (wiki_root / "scripts").is_dir()
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
    return wiki_root


def run_wiki_command(wiki_root: Path, python_path: Path, module: str, *args: str, required: bool = True) -> int:
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
    run_wiki_command(wiki_root, python_path, "scripts.update_wiki", "--wiki-root", str(wiki_root))
    run_wiki_command(wiki_root, python_path, "scripts.generate_module_wiki", "--wiki-root", str(wiki_root))
    run_wiki_command(
        wiki_root,
        python_path,
        "scripts.query_runtime.community_builder",
        "--wiki-root",
        str(wiki_root),
        "--top-per-module",
        "10",
    )
    question = smoke_question or f"What is the main responsibility of {project_name}?"
    run_wiki_command(
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
    print_context(None, wiki_root, python_path, args.repo, "backfill")
    run_onboarding_steps(wiki_root, python_path, args.repo, args.question)
    info("Verdict: PASS")


def command_sync(args: argparse.Namespace) -> None:
    repo_path = Path(args.repo).expanduser().resolve()
    wiki_root = Path(args.wiki_root).expanduser().resolve()
    project_name = infer_project_name(repo_path, args.project_name)
    python_path = ensure_python(wiki_root, install_requirements=args.install_requirements)
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
    backfill.add_argument("--install-requirements", action="store_true")
    backfill.set_defaults(func=command_backfill)

    sync = sub.add_parser("sync", help="Create or update repo sync diff state.")
    sync.add_argument("--repo", required=True)
    sync.add_argument("--wiki-root", required=True)
    sync.add_argument("--project-name")
    sync.add_argument("--target-ref", default="HEAD")
    sync.add_argument("--accept-baseline", action="store_true")
    sync.add_argument("--install-requirements", action="store_true")
    sync.set_defaults(func=command_sync)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
