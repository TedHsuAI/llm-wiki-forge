from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path

from llm_wiki_forge.resources import bootstrap_llm_wiki


RESOURCE_MODULES: dict[str, str] = {
    "scripts.update_wiki": bootstrap_llm_wiki.UPDATE_WIKI,
    "scripts.generate_module_wiki": bootstrap_llm_wiki.GENERATE_MODULE_WIKI,
    "scripts.query_runtime.community_builder": bootstrap_llm_wiki.COMMUNITY_BUILDER,
    "scripts.query_runtime.graph_runtime": bootstrap_llm_wiki.GRAPH_RUNTIME,
    "scripts.query_runtime.eval_queries": bootstrap_llm_wiki.EVAL_QUERIES,
    "scripts.repo_sync.diff_wiki": bootstrap_llm_wiki.DIFF_WIKI,
}

QUERY_RUNTIME_MODULES = [
    "scripts.query_runtime.challenge",
    "scripts.query_runtime.code_provider",
    "scripts.query_runtime.community_builder",
    "scripts.query_runtime.community_nav",
    "scripts.query_runtime.eval_queries",
    "scripts.query_runtime.extract_code",
    "scripts.query_runtime.graph_runtime",
    "scripts.query_runtime.hybrid_ranker",
    "scripts.query_runtime.io",
    "scripts.query_runtime.models",
    "scripts.query_runtime.planner",
    "scripts.query_runtime.query",
    "scripts.query_runtime.query_orchestrator",
    "scripts.query_runtime.router",
    "scripts.query_runtime.semantic",
    "scripts.query_runtime.source_search",
]


def _read_packaged_resource_module(module: str) -> str | None:
    parts = module.split(".")
    resource_path = resources.files("llm_wiki_forge").joinpath("resources", *parts[:-1], f"{parts[-1]}.py")
    try:
        return resource_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _read_packaged_module(module: str) -> str:
    resource_code = _read_packaged_resource_module(module)
    if resource_code is not None:
        return resource_code
    return RESOURCE_MODULES[module]


def _module_available(module: str) -> bool:
    return module in RESOURCE_MODULES or _read_packaged_resource_module(module) is not None


def packaged_module_available(module: str) -> bool:
    return _module_available(module)


def _write_package_file(root: Path, module: str, code: str) -> None:
    parts = module.split(".")
    package_dir = root
    for part in parts[:-1]:
        package_dir = package_dir / part
        package_dir.mkdir(parents=True, exist_ok=True)
        init_file = package_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")
    (package_dir / f"{parts[-1]}.py").write_text(code, encoding="utf-8")


def _resource_dependency_modules(module: str) -> list[str]:
    if module == "scripts.generate_module_wiki":
        return ["scripts.update_wiki", module]
    if module.startswith("scripts.query_runtime."):
        return QUERY_RUNTIME_MODULES
    return [module]


def run_packaged_module(
    python_path: Path,
    module: str,
    args: list[str],
    *,
    cwd: Path | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """Run a generated wiki helper from the Forge package, not from wiki_root/scripts."""

    if not _module_available(module):
        raise ValueError(f"No packaged LLM Wiki module is available for {module}")

    with tempfile.TemporaryDirectory(prefix="llm_wiki_forge_runtime_") as temp:
        temp_root = Path(temp)
        for dependency in _resource_dependency_modules(module):
            _write_package_file(temp_root, dependency, _read_packaged_module(dependency))

        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(temp_root) if not existing_pythonpath else f"{temp_root}{os.pathsep}{existing_pythonpath}"
        return subprocess.run(
            [str(python_path), "-m", module, *args],
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=stdout,
            stderr=stderr,
            text=text,
            check=False,
        )


def module_exists_on_path(python_path: Path, module: str, *, cwd: Path | None = None) -> bool:
    code = f"import importlib.util; raise SystemExit(0 if importlib.util.find_spec({module!r}) else 1)"
    result = subprocess.run(
        [str(python_path), "-c", code],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return result.returncode == 0


def first_existing_python(candidates: list[Path | str]) -> Path | None:
    for candidate in candidates:
        path = Path(candidate)
        if path.exists() and path.is_file():
            return path
        found = shutil.which(str(candidate))
        if found:
            return Path(found)
    return None
