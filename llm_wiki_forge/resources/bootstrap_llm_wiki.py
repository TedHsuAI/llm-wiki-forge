#!/usr/bin/env python3
"""Create a portable first-run LLM Wiki scaffold.

The generated scaffold keeps a stable wiki.scope.json and Wiki folder contract.
Graphify is a required generation dependency because module graphs are part of
the LLM Wiki evidence baseline.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SKIP_DIRS = {
    ".git",
    ".gradle",
    ".idea",
    ".vs",
    "bin",
    "build",
    "coverage",
    "obj",
    "node_modules",
    "packages",
    "TestResults",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return slug or "module"


def write_text(path: Path, content: str, overwrite: bool = False) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return False
    path.write_text(content, encoding="utf-8", newline="\n")
    return True


def write_json(path: Path, data: object, overwrite: bool = False) -> bool:
    return write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", overwrite)


UPDATE_WIKI = r'''from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SKIP_DIRS = {".git", ".gradle", ".idea", ".vs", "bin", "build", "coverage", "obj", "node_modules", "packages", "TestResults"}
PROJECT_EXTENSIONS = {".csproj"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_scope(root: Path) -> dict:
    return json.loads((root / "wiki.scope.json").read_text(encoding="utf-8"))


def resolve_path(root: Path, scope: dict, raw: str) -> Path:
    value = raw
    for key, replacement in scope.get("pathVariables", {}).items():
        value = value.replace("${" + key + "}", replacement)
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def is_under_any(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def normalize_project_path(base: Path, raw: str) -> Path:
    candidate = Path(raw.replace("\\", os.sep))
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def parse_solution_projects(solution_path: Path) -> tuple[list[Path], list[Path]]:
    active: list[Path] = []
    unloaded: list[Path] = []
    if not solution_path.exists():
        return active, unloaded
    text = solution_path.read_text(encoding="utf-8", errors="ignore")
    pattern = re.compile(r'^Project\("[^"]+"\)\s*=\s*"([^"]+)",\s*"([^"]+\.(?:csproj))",\s*"[^"]+"', re.MULTILINE | re.IGNORECASE)
    for match in pattern.finditer(text):
        name = match.group(1)
        raw_path = match.group(2)
        project_path = normalize_project_path(solution_path.parent, raw_path)
        lowered_name = name.lower()
        if "unavailable" in lowered_name or "unloaded" in lowered_name:
            unloaded.append(project_path)
        else:
            active.append(project_path)
    return active, unloaded


def parse_solution_filter_projects(filter_path: Path) -> tuple[list[Path], str | None]:
    if not filter_path.exists():
        return [], None
    try:
        data = json.loads(filter_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [], None
    solution = data.get("solution", {})
    solution_raw = solution.get("path")
    solution_path = normalize_project_path(filter_path.parent, solution_raw) if solution_raw else None
    solution_dir = solution_path.parent if solution_path else filter_path.parent
    projects: list[Path] = []
    for raw in solution.get("projects", []):
        if Path(raw).suffix.lower() not in PROJECT_EXTENSIONS:
            continue
        project_path = normalize_project_path(solution_dir, raw)
        if not project_path.exists():
            alternate = normalize_project_path(filter_path.parent, raw)
            if alternate.exists():
                project_path = alternate
        projects.append(project_path)
    return projects, str(solution_path) if solution_path else None


def sorted_paths(paths: list[Path]) -> list[str]:
    return sorted({str(path) for path in paths})


def count_csharp_files(path: Path, active_projects: list[Path], enforce_project_scope: bool) -> tuple[int, int]:
    scan_root = path.parent if path.is_file() else path
    active_roots = [project.parent for project in active_projects if project.exists()]
    csharp_count = 0
    skipped_csharp_count = 0
    if not scan_root.exists():
        return csharp_count, skipped_csharp_count
    for item in scan_root.rglob("*.cs"):
        if should_skip(item):
            continue
        if enforce_project_scope and active_roots and not is_under_any(item, active_roots):
            skipped_csharp_count += 1
            continue
        csharp_count += 1
    return csharp_count, skipped_csharp_count


def discover_source(path: Path) -> dict:
    if not path.exists():
        return {
            "exists": False,
            "projectFiles": [],
            "excludedProjectFiles": [],
            "missingProjectFiles": [],
            "solutionFiles": [],
            "solutionFilterFiles": [],
            "projectScopeSource": "missing",
            "csharpFiles": 0,
            "skippedCsharpFiles": 0,
        }
    all_project_files: list[Path] = []
    solution_files: list[Path] = []
    solution_filter_files: list[Path] = []
    scan_root = path.parent if path.is_file() else path
    candidates = [path] if path.is_file() else list(scan_root.rglob("*"))
    for item in candidates:
        if should_skip(item):
            continue
        if item.is_file() and item.suffix.lower() in PROJECT_EXTENSIONS:
            all_project_files.append(item.resolve())
        elif item.is_file() and item.suffix.lower() == ".sln":
            solution_files.append(item.resolve())
        elif item.is_file() and item.suffix.lower() == ".slnf":
            solution_filter_files.append(item.resolve())
    active_projects: list[Path] = []
    excluded_projects: list[Path] = []
    missing_projects: list[Path] = []
    project_scope_source = "project_discovery"
    if solution_filter_files:
        project_scope_source = "solution_filter"
        for filter_file in solution_filter_files:
            projects, solution_path = parse_solution_filter_projects(filter_file)
            active_projects.extend(projects)
            if solution_path:
                solution_files.append(Path(solution_path).resolve())
        active_set = {str(project) for project in active_projects}
        excluded_projects.extend([project for project in all_project_files if str(project) not in active_set])
    elif solution_files:
        project_scope_source = "solution"
        for solution_file in solution_files:
            projects, unloaded = parse_solution_projects(solution_file)
            active_projects.extend(projects)
            excluded_projects.extend(unloaded)
        active_set = {str(project) for project in active_projects}
        excluded_set = {str(project) for project in excluded_projects}
        excluded_projects.extend([project for project in all_project_files if str(project) not in active_set and str(project) not in excluded_set])
    else:
        active_projects = all_project_files
    missing_projects = [project for project in active_projects if not project.exists()]
    active_existing = [project for project in active_projects if project.exists()]
    enforce_project_scope = project_scope_source in {"solution_filter", "solution"} and bool(active_existing)
    csharp_count, skipped_csharp_count = count_csharp_files(path, active_existing, enforce_project_scope)
    return {
        "exists": True,
        "projectFiles": sorted_paths(active_existing),
        "excludedProjectFiles": sorted_paths(excluded_projects),
        "missingProjectFiles": sorted_paths(missing_projects),
        "solutionFiles": sorted_paths(solution_files),
        "solutionFilterFiles": sorted_paths(solution_filter_files),
        "projectScopeSource": project_scope_source,
        "csharpFiles": csharp_count,
        "skippedCsharpFiles": skipped_csharp_count,
    }


def iter_targets(root: Path, scope: dict):
    for repo in scope.get("repos", []):
        if repo.get("include") is False:
            continue
        targets = repo.get("targets") or [repo]
        for target in targets:
            if target.get("include") is False:
                continue
            raw_path = target.get("actualPath") or repo.get("actualRoot")
            if not raw_path:
                continue
            resolved = resolve_path(root, scope, raw_path)
            yield repo, target, raw_path, resolved


def target_exclude_paths(root: Path, scope: dict, repo: dict, target: dict) -> tuple[list[str], list[str]]:
    raw_paths = []
    raw_paths.extend(repo.get("excludePaths") or [])
    raw_paths.extend(target.get("excludePaths") or [])
    resolved_paths = [str(resolve_path(root, scope, str(raw))) for raw in raw_paths]
    return [str(raw) for raw in raw_paths], resolved_paths


def build_inventory(root: Path) -> dict:
    scope = load_scope(root)
    items = []
    for repo, target, raw_path, resolved in iter_targets(root, scope):
        probe = discover_source(resolved)
        exclude_paths, resolved_exclude_paths = target_exclude_paths(root, scope, repo, target)
        items.append({
            "repo": repo.get("logicalName"),
            "logicalName": target.get("logicalName") or repo.get("logicalName"),
            "actualPath": raw_path,
            "resolvedPath": str(resolved),
            "excludePaths": exclude_paths,
            "resolvedExcludePaths": resolved_exclude_paths,
            "type": target.get("type", "project-root"),
            "exists": probe["exists"],
            "projectFiles": probe["projectFiles"],
            "excludedProjectFiles": probe["excludedProjectFiles"],
            "missingProjectFiles": probe["missingProjectFiles"],
            "solutionFiles": probe["solutionFiles"],
            "solutionFilterFiles": probe["solutionFilterFiles"],
            "projectScopeSource": probe["projectScopeSource"],
            "csharpFiles": probe["csharpFiles"],
            "skippedCsharpFiles": probe["skippedCsharpFiles"],
        })
    return {"generatedAt": now_iso(), "items": items}


def command_status(name: str, required_for: str, blocked_when_missing: str) -> dict:
    command = shutil.which(name)
    return {
        "Tool": name,
        "Available": bool(command),
        "Command": command or "(not found)",
        "RequiredFor": required_for,
        "BlockedWhenMissing": blocked_when_missing,
        "Note": "Resolved from PATH." if command else f"Missing from PATH. Blocks {blocked_when_missing}.",
    }


def command_version(command: str) -> str | None:
    path = shutil.which(command)
    if not path:
        return None
    try:
        result = subprocess.run([path, "--version"], text=True, capture_output=True, check=False, timeout=10)
    except Exception:
        return None
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0] if output else None


def module_status(module: str, distribution: str | None = None) -> dict:
    available = importlib.util.find_spec(module) is not None
    version = None
    if distribution:
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            version = None
    return {
        "module": module,
        "distribution": distribution or module,
        "available": available,
        "version": version,
    }


def build_tooling_status() -> dict:
    tools = [
        command_status(
            "graphify",
            "scope-locked graph extraction; architecture evidence extraction",
            "graph extraction and graph-backed evidence stages",
        ),
        command_status(
            "repomix",
            "repo/source bundling; focused source packing",
            "repomix-based source bundling",
        ),
        command_status(
            "dotnet",
            "dotnet project inspection; solution and project metadata discovery",
            "dotnet project inspection and build-assisted discovery",
        ),
        command_status(
            "node",
            "deck/report helper scripts and JavaScript tooling",
            "JavaScript helper scripts",
        ),
        command_status(
            "npm",
            "JavaScript tooling installation and helper scripts",
            "npm-based helper tooling",
        ),
    ]
    return {
        "generatedAt": now_iso(),
        "tools": tools,
        "missingTools": [tool["Tool"] for tool in tools if not tool["Available"]],
    }


def build_query_runtime_status() -> dict:
    modules = [
        module_status("graphify", "graphifyy"),
        module_status("langgraph"),
        module_status("tree_sitter", "tree-sitter"),
        module_status("tree_sitter_c_sharp", "tree-sitter-c-sharp"),
        module_status("tree_sitter_kotlin", "tree-sitter-kotlin"),
        module_status("tree_sitter_java", "tree-sitter-java"),
        module_status("graphrag"),
    ]
    return {
        "generated_at": now_iso(),
        "python": sys.version.split()[0],
        "executables": {
            "python": sys.executable,
            "node": command_version("node"),
            "npm": command_version("npm"),
        },
        "modules": modules,
        "missing_required_modules": [
            item["module"]
            for item in modules
            if item["module"] in {"graphify", "langgraph", "tree_sitter", "tree_sitter_c_sharp"} and not item["available"]
        ],
        "optional_modules": ["tree_sitter_kotlin", "tree_sitter_java", "graphrag"],
    }


def render_markdown(inventory: dict) -> str:
    lines = ["# Scope Inventory", "", f"Generated: {inventory['generatedAt']}", ""]
    for item in inventory["items"]:
        lines.extend([
            f"## {item['logicalName']}",
            "",
            f"- repo: `{item['repo']}`",
            f"- path: `{item['actualPath']}`",
            f"- resolved: `{item['resolvedPath']}`",
            f"- exists: `{item['exists']}`",
            f"- project scope source: `{item.get('projectScopeSource', 'unknown')}`",
            f"- csharp files: `{item['csharpFiles']}`",
            f"- skipped csharp files: `{item.get('skippedCsharpFiles', 0)}`",
            f"- active projects: `{len(item.get('projectFiles', []))}`",
            f"- excluded projects: `{len(item.get('excludedProjectFiles', []))}`",
            "",
        ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki-root", default=".")
    args = parser.parse_args()
    root = Path(args.wiki_root).resolve()
    inventory = build_inventory(root)
    (root / "Wiki" / "_data").mkdir(parents=True, exist_ok=True)
    (root / "Wiki" / "_data" / "scope.inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "Wiki" / "00_Scope_Inventory.md").write_text(render_markdown(inventory), encoding="utf-8", newline="\n")
    (root / "Wiki" / "_data" / "tooling.status.json").write_text(json.dumps(build_tooling_status(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "Wiki" / "_data" / "query_runtime.status.json").write_text(json.dumps(build_query_runtime_status(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "Wiki" / "00_System_Index.md").write_text("# System Index\n\nBootstrap scaffold. Run generate_module_wiki next.\n", encoding="utf-8", newline="\n")
    print(f"scope inventory items: {len(inventory['items'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


GENERATE_MODULE_WIKI = r'''from __future__ import annotations

import argparse
import collections
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.update_wiki import build_inventory, is_under_any


CODE_EXTENSIONS = {".cs", ".kt", ".kts", ".java"}
ANDROID_BUILD_FILES = {"settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts"}
SKIP_PARTS = {
    ".git",
    ".gradle",
    ".idea",
    ".vs",
    "bin",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "obj",
    "packages",
    "testresults",
}
ENTRY_HINTS = (
    "Activity",
    "Application",
    "Controller",
    "Fragment",
    "Handler",
    "Job",
    "Repository",
    "Service",
    "Startup",
    "ViewModel",
    "Worker",
)
NOISE_WORDS = {
    "abstract",
    "activity",
    "android",
    "base",
    "common",
    "config",
    "configuration",
    "constant",
    "constants",
    "controller",
    "data",
    "default",
    "dto",
    "entity",
    "enum",
    "exception",
    "extension",
    "extensions",
    "fragment",
    "helper",
    "helpers",
    "interface",
    "internal",
    "java",
    "job",
    "kotlin",
    "manager",
    "model",
    "models",
    "option",
    "options",
    "program",
    "provider",
    "repo",
    "repository",
    "request",
    "response",
    "service",
    "settings",
    "startup",
    "system",
    "task",
    "test",
    "tests",
    "type",
    "utils",
    "viewmodel",
    "worker",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-").lower() or "module"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_scope(root: Path) -> dict[str, Any]:
    scope_path = root / "wiki.scope.json"
    if not scope_path.exists():
        return {}
    return load_json(scope_path)


def resolve_metadata_path(wiki_root: Path, scope: dict[str, Any], raw_path: str) -> Path:
    expanded = str(raw_path)
    for key, value in (scope.get("pathVariables") or {}).items():
        token = "${" + str(key) + "}"
        if token in expanded:
            expanded = expanded.replace(token, str(resolve_metadata_path(wiki_root, scope, str(value))))
    path = Path(expanded)
    if not path.is_absolute():
        path = wiki_root / path
    return path.resolve()


def metadata_child(raw_root: str, relative: Path) -> str:
    base = str(raw_root).replace("\\", "/").rstrip("/")
    rel = relative.as_posix()
    return f"{base}/{rel}" if rel else base


def metadata_text(path: Path, wiki_root: Path, scope: dict[str, Any]) -> str:
    resolved = path.resolve()
    for key, value in sorted((scope.get("pathVariables") or {}).items()):
        variable_root = resolve_metadata_path(wiki_root, scope, str(value)).resolve()
        if resolved == variable_root or variable_root in resolved.parents:
            relative = os.path.relpath(resolved, variable_root).replace("\\", "/")
            return "${" + str(key) + "}" if relative == "." else "${" + str(key) + "}/" + relative
    return os.path.relpath(resolved, wiki_root).replace("\\", "/")


def should_skip(path: Path) -> bool:
    return any(part.lower() in SKIP_PARTS for part in path.parts)


def split_words(value: str) -> list[str]:
    words: list[str] = []
    for chunk in re.split(r"[^A-Za-z0-9]+", value):
        if not chunk:
            continue
        parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", chunk).split()
        words.extend(part.lower() for part in parts if len(part) >= 3)
    return [word for word in words if word not in NOISE_WORDS]


def platform_markers(source: Path) -> dict[str, bool]:
    if not source.exists():
        return {
            "hasAndroidBuildFile": False,
            "hasAndroidManifest": False,
            "hasCsharpProject": False,
        }
    scan_root = source.parent if source.is_file() else source
    return {
        "hasAndroidBuildFile": any((scan_root / name).exists() for name in ANDROID_BUILD_FILES),
        "hasAndroidManifest": any(scan_root.rglob("AndroidManifest.xml")),
        "hasCsharpProject": any(scan_root.rglob("*.csproj")),
    }


def detect_platform(source: Path) -> str:
    if not source.exists():
        return "unknown"
    scan_root = source.parent if source.is_file() else source
    markers = platform_markers(source)
    has_android_build = markers["hasAndroidBuildFile"]
    has_android_manifest = markers["hasAndroidManifest"]
    has_csharp_project = markers["hasCsharpProject"]
    if (has_android_build or has_android_manifest) and has_csharp_project:
        return "mixed"
    if has_android_build:
        return "android"
    if has_android_manifest:
        return "android"
    if has_csharp_project:
        return "csharp"
    if any(scan_root.rglob("*.kt")) or any(scan_root.rglob("*.java")):
        return "android"
    return "unknown"


def platform_detection(source: Path) -> dict[str, Any]:
    if not source.exists():
        return {
            "hasAndroidBuildFile": False,
            "hasAndroidManifest": False,
            "hasCsharpProject": False,
            "guard": "missing_source",
        }
    markers = platform_markers(source)
    has_android_build = markers["hasAndroidBuildFile"]
    has_android_manifest = markers["hasAndroidManifest"]
    has_csharp_project = markers["hasCsharpProject"]
    guard = "mixed_android_csharp_blocked" if (has_android_build or has_android_manifest) and has_csharp_project else "none"
    return {
        **markers,
        "guard": guard,
    }


def source_files_for_item(item: dict[str, Any], platform: str) -> list[Path]:
    source = Path(item["resolvedPath"])
    if not source.exists():
        return []
    scan_root = source.parent if source.is_file() else source
    excluded_roots = [Path(path).resolve() for path in item.get("resolvedExcludePaths") or []]
    if platform == "csharp":
        active_roots = [Path(project).resolve().parent for project in item.get("projectFiles") or [] if Path(project).exists()]
        enforce_scope = item.get("projectScopeSource") in {"solution_filter", "solution"} and bool(active_roots)
        files = []
        for path in scan_root.rglob("*.cs"):
            if should_skip(path):
                continue
            if excluded_roots and is_under_any(path, excluded_roots):
                continue
            if enforce_scope and not is_under_any(path, active_roots):
                continue
            files.append(path.resolve())
        return sorted(files)

    if platform != "android":
        return []

    extensions = {".kt", ".kts", ".java"}
    files = []
    for path in scan_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in extensions or should_skip(path):
            continue
        if excluded_roots and is_under_any(path, excluded_roots):
            continue
        lowered = path.as_posix().lower()
        if "/src/test/" in lowered or "/src/androidtest/" in lowered:
            continue
        files.append(path.resolve())
    return sorted(files)


def extract_symbols(text: str, suffix: str) -> list[dict[str, str]]:
    symbols: list[dict[str, str]] = []
    if suffix == ".cs":
        pattern = r"\b(class|interface|record|struct|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"
    elif suffix in {".kt", ".kts"}:
        pattern = r"\b(class|interface|object|enum\s+class|fun)\s+([A-Za-z_][A-Za-z0-9_]*)"
    else:
        pattern = r"\b(class|interface|record|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"
    for match in re.finditer(pattern, text):
        kind = match.group(1).replace(" ", "_")
        symbols.append({"kind": kind, "name": match.group(2)})
        if len(symbols) >= 40:
            break
    return symbols


def extract_methods(text: str, suffix: str) -> list[str]:
    if suffix in {".kt", ".kts"}:
        names = re.findall(r"\bfun\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text)
    elif suffix == ".java":
        names = re.findall(r"\b(?:public|private|protected|static|final|\s)+[\w<>\[\],\s?]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text)
    else:
        names = re.findall(
            r"(?:public|private|protected|internal|static|async|virtual|override|sealed|partial|\s)+"
            r"[\w<>\[\],\s?]+?\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            text,
        )
    blocked = {"if", "for", "foreach", "while", "switch", "catch", "using", "lock"}
    return [name for name in names if name not in blocked][:80]


def extract_csharp_routes(text: str) -> list[str]:
    routes = []
    for match in re.finditer(r"\[(?:Route|HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch)\s*(?:\(\s*\"([^\"]+)\"\s*\))?", text):
        routes.append(match.group(1) or match.group(0).strip("[]"))
    return routes[:40]


CONST_VAL_RE = re.compile(r"\bconst\s+val\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\r\n]+)")


def kotlin_const_assignments(text: str) -> dict[str, str]:
    return {match.group(1): match.group(2).strip() for match in CONST_VAL_RE.finditer(text)}


def resolve_kotlin_const_expr(
    expr: str,
    local_constants: dict[str, str],
    base_constants: dict[str, str],
    seen: set[str],
) -> str | None:
    # ponytail: const string + identifier only; add template/function support if Android routes start using it.
    parts: list[str] = []
    for raw_part in expr.split("+"):
        part = raw_part.strip()
        string_match = re.fullmatch(r"\"([^\"]*)\"", part)
        if string_match:
            parts.append(string_match.group(1))
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part):
            if part in seen:
                return None
            value = (
                resolve_kotlin_const_expr(local_constants[part], local_constants, base_constants, seen | {part})
                if part in local_constants
                else base_constants.get(part)
            )
            if value is None:
                return None
            parts.append(value)
            continue
        return None
    return "".join(parts)


def resolve_kotlin_string_constants(text: str, base_constants: dict[str, str] | None = None) -> dict[str, str]:
    local_constants = kotlin_const_assignments(text)
    constants = dict(base_constants or {})
    for name, expr in local_constants.items():
        value = resolve_kotlin_const_expr(expr, local_constants, constants, {name})
        if value is not None:
            constants[name] = value
    return constants


def collect_kotlin_string_constants(files: list[Path]) -> dict[str, str]:
    constants: dict[str, str] = {}
    for path in files:
        if path.suffix.lower() not in {".kt", ".kts"}:
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        constants.update(resolve_kotlin_string_constants(text, constants))
    return constants


def extract_retrofit_surface(text: str, base_constants: dict[str, str] | None = None) -> list[str]:
    surface = []
    constants = resolve_kotlin_string_constants(text, base_constants)
    for match in re.finditer(
        r"@(GET|POST|PUT|DELETE|PATCH)\s*\(\s*(?:\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*))",
        text,
    ):
        surface.append(f"{match.group(1)} {match.group(2) or constants.get(match.group(3), match.group(3))}")
    return surface[:40]


def classify_entry(path: Path, text: str, symbols: list[dict[str, str]], platform: str) -> str:
    haystack = f"{path.as_posix()} {' '.join(symbol.get('name', '') for symbol in symbols)}".lower()
    if platform == "android":
        if "@composable" in text.lower():
            return "compose_ui"
        if "retrofit2.http" in text or re.search(r"@(GET|POST|PUT|DELETE|PATCH)\s*\(", text):
            return "retrofit_api"
        if "viewmodel" in haystack:
            return "view_model"
        if "repository" in haystack:
            return "repository"
        if "activity" in haystack:
            return "activity"
        if "fragment" in haystack:
            return "fragment"
        if "module" in haystack and ("koin" in text.lower() or "dagger" in text.lower() or "hilt" in text.lower()):
            return "di_registration"
    if "controller" in haystack:
        return "api_controller"
    if "hostedservice" in haystack or "backgroundservice" in haystack or "worker" in haystack:
        return "background_worker"
    if "handler" in haystack:
        return "handler"
    if "repository" in haystack:
        return "repository"
    if "service" in haystack:
        return "service"
    if path.name in {"Program.cs", "Startup.cs"}:
        return "application_bootstrap"
    return "source_file"


def scan_sources(item: dict[str, Any], platform: str, files: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source = Path(item["resolvedPath"])
    scan_root = source.parent if source.is_file() else source
    entries: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    raw_root = str(item["actualPath"])
    kotlin_constants = collect_kotlin_string_constants(files) if platform == "android" else {}
    for path in files:
        rel = path.relative_to(scan_root)
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        file_symbols = extract_symbols(text, path.suffix.lower())
        methods = extract_methods(text, path.suffix.lower())
        entry_kind = classify_entry(rel, text, file_symbols, platform)
        routes = extract_csharp_routes(text) if platform == "csharp" else extract_retrofit_surface(text, kotlin_constants)
        score = sum(2 for hint in ENTRY_HINTS if hint.lower() in path.name.lower())
        score += 4 if routes else 0
        score += 3 if entry_kind != "source_file" else 0
        score += 1 if methods else 0
        source_path = metadata_child(raw_root, rel)
        entry = {
            "file": source_path,
            "relative_file": rel.as_posix(),
            "kind": entry_kind,
            "entryKind": entry_kind,
            "entryScore": score,
            "symbols": file_symbols[:30],
            "methods": [{"name": name} for name in methods[:40]],
            "routes": routes,
            "route_surface": routes,
        }
        entries.append(entry)
        for symbol in file_symbols:
            name = symbol.get("name") or Path(source_path).stem
            symbols.append(
                {
                    "id": f"{slug(item['logicalName'])}.{name}",
                    "name": name,
                    "kind": symbol.get("kind") or "symbol",
                    "solution_group": item.get("repo") or item.get("logicalName"),
                    "module": item["logicalName"],
                    "project": item["logicalName"],
                    "source_paths": [source_path],
                    "business_context": " ".join(split_words(source_path)),
                    "skill_description": entry_kind,
                    "technical_contract": {
                        "route_surface": routes,
                        "public_methods": methods[:40],
                    },
                }
            )
    entries.sort(key=lambda entry: int(entry.get("entryScore") or 0), reverse=True)
    return entries, symbols


def summarize_terms(name: str, entries: list[dict[str, Any]]) -> list[str]:
    counter: collections.Counter[str] = collections.Counter(split_words(name))
    for entry in entries:
        counter.update(split_words(str(entry.get("file") or "")))
        counter.update(split_words(str(entry.get("kind") or "")))
        for symbol in entry.get("symbols") or []:
            counter.update(split_words(str(symbol.get("name") or "")))
        for method in entry.get("methods") or []:
            counter.update(split_words(str(method.get("name") or "")))
        for route in entry.get("route_surface") or []:
            counter.update(split_words(str(route)))
    return [word for word, _ in counter.most_common(40)]


def discover_android_surfaces(source: Path, excluded_roots: list[Path] | None = None) -> dict[str, Any]:
    scan_root = source.parent if source.is_file() else source
    excluded_roots = excluded_roots or []
    gradle_files = [
        str(path.relative_to(scan_root)).replace("\\", "/")
        for name in ANDROID_BUILD_FILES
        for path in scan_root.rglob(name)
        if not should_skip(path) and not is_under_any(path, excluded_roots)
    ][:80]
    manifests = []
    manifest_components: list[str] = []
    for manifest in scan_root.rglob("AndroidManifest.xml"):
        if should_skip(manifest) or is_under_any(manifest, excluded_roots):
            continue
        rel = str(manifest.relative_to(scan_root)).replace("\\", "/")
        manifests.append(rel)
        text = manifest.read_text(encoding="utf-8-sig", errors="replace")
        for tag in ("activity", "service", "receiver", "provider", "application"):
            for match in re.finditer(rf"<{tag}\b[^>]*android:name=\"([^\"]+)\"", text):
                manifest_components.append(f"{tag}:{match.group(1)}")
    return {
        "gradle_modules": gradle_files,
        "manifest_components": manifest_components[:120],
        "manifest_files": manifests[:40],
    }


def graphify_workspace(wiki_root: Path, scope: dict[str, Any]) -> Path:
    tooling = ((scope.get("tooling") or {}).get("graphify") or {})
    raw = tooling.get("workspaceSubdir") or "Wiki/_data/graphify-work"
    return resolve_metadata_path(wiki_root, scope, str(raw))


def run_graphify_shard(
    wiki_root: Path,
    scope: dict[str, Any],
    module_id: str,
    source_root: Path,
    files: list[Path],
) -> dict[str, Any]:
    shard_root = graphify_workspace(wiki_root, scope) / "shards" / module_id
    graph_out = shard_root / "graphify-out"
    graph_json = graph_out / "graph.json"
    report_path = graph_out / "GRAPH_REPORT.md"
    try:
        from graphify.analyze import god_nodes, surprising_connections, suggest_questions
        from graphify.build import build_from_json
        from graphify.cluster import cluster, score_all
        from graphify.export import to_json
        from graphify.extract import extract
        from graphify.report import generate
    except Exception as exc:
        raise RuntimeError(
            "Graphify is required for LLM Wiki generation. "
            "Install the PyPI package `graphifyy>=0.4.10,<0.9`, which provides the `graphify` module."
        ) from exc

    try:
        graph_out.mkdir(parents=True, exist_ok=True)
        extraction = extract(files)
        graph = build_from_json(extraction)
        communities = cluster(graph)
        scores = score_all(graph, communities)
        labels = {community_id: f"community-{community_id}" for community_id in communities}
        to_json(graph, communities, str(graph_json))
        report = generate(
            graph,
            communities,
            scores,
            labels,
            god_nodes(graph),
            surprising_connections(graph, communities),
            {"total_files": len(files), "total_words": 0},
            {"input": extraction.get("input_tokens", 0), "output": extraction.get("output_tokens", 0)},
            str(source_root),
            suggest_questions(graph, communities, labels),
        )
        report_path.write_text(report, encoding="utf-8")
        return {
            "status": "enabled",
            "strategy": "shard",
            "mode": "python-api-ast",
            "corpus_path": metadata_text(source_root, wiki_root, scope),
            "shard_path": metadata_text(shard_root, wiki_root, scope),
            "graph_json_path": metadata_text(graph_json, wiki_root, scope),
            "report_path": metadata_text(report_path, wiki_root, scope),
            "total_files": len(files),
            "code_files": len(files),
            "non_code_files": 0,
            "module_nodes": graph.number_of_nodes(),
            "graph_edges": graph.number_of_edges(),
            "communities": len(communities),
            "cross_edges": 0,
            "god_nodes": god_nodes(graph),
            "note": "Graphify shard generated from scoped source files.",
        }
    except Exception as exc:
        raise RuntimeError(f"Graphify failed while generating shard `{module_id}`: {exc}") from exc


def build_module(
    wiki_root: Path,
    scope: dict[str, Any],
    item: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    name = str(item["logicalName"])
    module_id = slug(name)
    source = Path(item["resolvedPath"])
    platform = detect_platform(source)
    detection = platform_detection(source)
    files = source_files_for_item(item, platform)
    entries, symbols = scan_sources(item, platform, files)
    entry_points = [entry for entry in entries if int(entry.get("entryScore") or 0) > 0] or entries[:25]
    terms = summarize_terms(name, entries)
    excluded_roots = [Path(path).resolve() for path in item.get("resolvedExcludePaths") or []]
    android = discover_android_surfaces(source, excluded_roots) if platform == "android" and source.exists() else {}
    guard_note = (
        "Mixed Android and C# project markers were found under this target; source scanning was blocked. "
        "Split wiki.scope.json targets to the Android and C# project roots before generating module evidence."
    )
    graphify = run_graphify_shard(wiki_root, scope, module_id, source.parent if source.is_file() else source, files) if files else {
        "status": "blocked" if platform == "mixed" else "empty",
        "strategy": "shard",
        "mode": "python-api-ast",
        "graph_json_path": None,
        "report_path": None,
        "module_nodes": 0,
        "graph_edges": 0,
        "communities": 0,
        "note": guard_note if platform == "mixed" else "No scoped code files were available for Graphify.",
    }
    technical_contract = {
        "entry_points": entry_points,
        "entryPoints": entry_points,
        "route_surface": [route for entry in entry_points for route in (entry.get("route_surface") or [])][:80],
        "routeSurface": [entry["file"] for entry in entry_points[:40]],
        "dependencies": [],
        "projectFiles": item.get("projectFiles", []),
        "excludedProjectFiles": item.get("excludedProjectFiles", []),
        "excludePaths": item.get("excludePaths", []),
        "resolvedExcludePaths": item.get("resolvedExcludePaths", []),
        "missingProjectFiles": item.get("missingProjectFiles", []),
        "solutionFiles": item.get("solutionFiles", []),
        "solutionFilterFiles": item.get("solutionFilterFiles", []),
        "projectScopeSource": item.get("projectScopeSource", "project_discovery"),
        "platformDetection": detection,
        "graphify": graphify,
        **android,
    }
    module = {
        "id": module_id,
        "name": name,
        "logicalName": name,
        "kind": "android-app" if platform == "android" else "csharp-module" if platform == "csharp" else "mixed-source" if platform == "mixed" else "source-module",
        "platform": platform,
        "solution_group": item.get("repo") or name,
        "project": name,
        "source_paths": [str(item["actualPath"])],
        "sourcePath": item["actualPath"],
        "resolvedPath": item["resolvedPath"],
        "generated_at": now_iso(),
        "generatedAt": now_iso(),
        "business_context": {
            "summary": f"{name} source extraction seed generated from {platform} static discovery.",
            "terms": terms or [name],
        },
        "business_tags": terms[:20],
        "skill_description": "Static module seed with Graphify community navigation metadata.",
        "graphify": graphify,
        "tooling": {
            "generator": "llm_wiki_forge.resources.scripts.generate_module_wiki",
            "platform": platform,
        },
        "technical_contract": technical_contract,
        "technicalContract": technical_contract,
        "impact_analysis": {
            "entry_file_count": len(entry_points),
            "source_file_count": len(files),
        },
        "dependencies": [],
        "callers": [],
        "callees": [],
        "exceptions": [],
        "risk_notes": [
            "Generated by static discovery; business semantics should be refined by overlays or reviewed wiki notes.",
            "No method-level full call graph is claimed; query runtime must use direct source evidence for detailed answers.",
        ] + ([guard_note] if platform == "mixed" else []),
        "riskNotes": [
            "Generated by static discovery; business semantics should be refined by overlays or reviewed wiki notes.",
            "No method-level full call graph is claimed; query runtime must use direct source evidence for detailed answers.",
        ] + ([guard_note] if platform == "mixed" else []),
        "confidence": {
            "level": "medium" if files else "low",
            "source": "static-discovery+graphify" if graphify.get("status") == "enabled" else "static-discovery",
        },
        "semanticCard": {
            "business_terms": terms or [name],
            "entry_symbols": [f"{entry['file']} :: {symbol.get('name')}" for entry in entry_points for symbol in entry.get("symbols", [])][:80],
            "entry_files": [entry["file"] for entry in entry_points[:80]],
        },
    }
    return module, symbols


def render_module(module: dict[str, Any]) -> str:
    graphify = module.get("graphify") or {}
    contract = module.get("technical_contract") or {}
    lines = [
        f"# {module['name']}",
        "",
        f"Platform: `{module.get('platform')}`",
        f"Source path: `{module.get('sourcePath')}`",
        "",
        "## Graphify",
        "",
        f"- status: `{graphify.get('status')}`",
        f"- strategy: `{graphify.get('strategy')}`",
        f"- mode: `{graphify.get('mode')}`",
        f"- nodes: `{graphify.get('module_nodes', 0)}`",
        f"- edges: `{graphify.get('graph_edges', 0)}`",
        f"- communities: `{graphify.get('communities', 0)}`",
        "",
        "## Entry Points",
        "",
    ]
    for entry in contract.get("entry_points", [])[:40]:
        names = ", ".join(symbol.get("name", "") for symbol in entry.get("symbols", [])[:5])
        suffix = f" - {names}" if names else ""
        routes = ", ".join(entry.get("route_surface", [])[:5])
        route_suffix = f" routes: {routes}" if routes else ""
        lines.append(f"- `{entry.get('file')}` ({entry.get('kind')}){suffix}{route_suffix}")
    if not contract.get("entry_points"):
        lines.append("- No entry points found.")
    lines.extend(["", "## Risk Notes", ""])
    lines.extend(f"- {note}" for note in module.get("risk_notes") or [])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate LLM Wiki module and symbol data")
    parser.add_argument("--wiki-root", default=".")
    args = parser.parse_args(argv)
    wiki_root = Path(args.wiki_root).resolve()
    scope = load_scope(wiki_root)
    inventory = build_inventory(wiki_root)
    data_modules = wiki_root / "Wiki" / "_data" / "modules"
    data_symbols = wiki_root / "Wiki" / "_data" / "symbols"
    modules_md = wiki_root / "Wiki" / "01_Modules"
    symbols_md = wiki_root / "Wiki" / "02_Symbols"
    for folder in (data_modules, data_symbols, modules_md, symbols_md):
        folder.mkdir(parents=True, exist_ok=True)

    built = 0
    for item in inventory.get("items") or []:
        if not item.get("exists"):
            continue
        module, symbols = build_module(wiki_root, scope, item)
        module_id = module["id"]
        write_json(data_modules / f"{module_id}.json", module)
        module_dir = modules_md / module_id
        module_dir.mkdir(parents=True, exist_ok=True)
        (module_dir / f"{module_id}.md").write_text(render_module(module), encoding="utf-8", newline="\n")
        symbol_payload = {
            "module": module["name"],
            "module_id": module_id,
            "generated_at": now_iso(),
            "symbols": symbols,
        }
        for symbol in symbols:
            write_json(data_symbols / f"{symbol['id']}.json", symbol)
        write_json(data_symbols / f"{module_id}.json", symbol_payload)
        symbol_dir = symbols_md / module_id
        symbol_dir.mkdir(parents=True, exist_ok=True)
        (symbol_dir / "_index.md").write_text(f"# {module['name']} Symbols\n\nSymbol seed count: {len(symbols)}\n", encoding="utf-8", newline="\n")
        built += 1
    print(f"modules built: {built}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

'''


COMMUNITY_BUILDER = r'''from __future__ import annotations

import argparse
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .io import load_json, load_modules, slugify, write_json


SEMANTIC_NOISE_WORDS = {
    "abstract",
    "activity",
    "adapter",
    "android",
    "api",
    "application",
    "base",
    "common",
    "config",
    "configuration",
    "constant",
    "constants",
    "controller",
    "cs",
    "data",
    "default",
    "dto",
    "entity",
    "enum",
    "exception",
    "extension",
    "extensions",
    "fragment",
    "gradle",
    "handler",
    "helper",
    "helpers",
    "implements",
    "interface",
    "internal",
    "java",
    "json",
    "kotlin",
    "kt",
    "kts",
    "manager",
    "model",
    "models",
    "option",
    "options",
    "program",
    "provider",
    "rd",
    "repo",
    "repository",
    "request",
    "response",
    "service",
    "services",
    "settings",
    "startup",
    "system",
    "task",
    "test",
    "tests",
    "tgds",
    "type",
    "utils",
    "viewmodel",
    "webapi",
    "worker",
    "xml",
}


def node_label(node: dict[str, Any]) -> str:
    return str(node.get("label") or node.get("id") or "")


def split_terms(value: str, *, drop_noise: bool = True) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    terms: list[str] = []
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9]*|[0-9]+|[\u4e00-\u9fff]{2,}", text):
        term = raw.lower()
        if len(term) <= 1:
            continue
        if drop_noise and term in SEMANTIC_NOISE_WORDS:
            continue
        terms.append(term)
    return terms


def top_terms(values: list[str], limit: int = 12, *, drop_noise: bool = True) -> list[str]:
    counter: Counter[str] = Counter()
    for value in values:
        counter.update(split_terms(value, drop_noise=drop_noise))
    return [term for term, _ in counter.most_common(limit)]


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _load_path_variables(wiki_root: Path) -> dict[str, str]:
    scope = _load_scope(wiki_root)
    return {str(key): str(value) for key, value in (scope.get("pathVariables") or {}).items()}


def _load_scope(wiki_root: Path) -> dict[str, Any]:
    scope_path = wiki_root / "wiki.scope.json"
    if not scope_path.exists():
        return {}
    return load_json(scope_path)


def _expand_path_variables(path_text: str, base_dir: Path, path_variables: dict[str, str]) -> str:
    expanded = path_text
    for key, value in path_variables.items():
        token = "${" + key + "}"
        if token not in expanded:
            continue
        root = Path(value) if len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"} else _path_from_wiki_metadata(value, base_dir, {})
        expanded = expanded.replace(token, str(root))
    if "${" in expanded:
        raise ValueError(f"Unresolved path variable in Hermes metadata path: {path_text}")
    return expanded


def _path_from_wiki_metadata(raw_path: str, base_dir: Path, path_variables: dict[str, str] | None = None) -> Path:
    path_text = str(raw_path or "").strip()
    if not path_text:
        return Path(path_text)

    was_variable_path = "${" in path_text
    path_text = _expand_path_variables(path_text, base_dir, path_variables or {})

    if len(path_text) >= 3 and path_text[1] == ":" and path_text[2] in {"\\", "/"}:
        if not was_variable_path:
            raise ValueError(f"Hermes metadata must use WSL or wiki-relative paths: {path_text}")
        return Path(path_text)

    if os.name != "nt" and path_text.startswith("/"):
        return Path(path_text.replace("\\", "/"))

    normalized = path_text.replace("\\", "/") if os.name != "nt" else path_text
    path = Path(normalized)
    if not path.is_absolute():
        return base_dir / path
    return path


def _metadata_text(path: Path, base_dir: Path, path_variables: dict[str, str]) -> str:
    resolved_path = path.resolve()
    for key, value in sorted(path_variables.items()):
        variable_root = (
            Path(value)
            if len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"}
            else _path_from_wiki_metadata(value, base_dir, {})
        ).resolve()
        if resolved_path == variable_root or variable_root in resolved_path.parents:
            relative = os.path.relpath(resolved_path, variable_root).replace("\\", "/")
            if relative == ".":
                return "${" + key + "}"
            return "${" + key + "}/" + relative
    if path.is_absolute():
        try:
            return os.path.relpath(path, base_dir).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")
    return str(path).replace("\\", "/")


def node_file(node: dict[str, Any], wiki_root: Path, path_variables: dict[str, str], source_root: Path | None = None) -> str:
    raw = str(node.get("source_file") or "")
    if raw in {"", "."}:
        return ""
    if len(raw) >= 3 and raw[1] == ":" and raw[2] in {"\\", "/"}:
        return _metadata_text(Path(raw), wiki_root, path_variables)
    path = Path(raw.replace("\\", "/"))
    if source_root is not None and not path.is_absolute() and "${" not in raw:
        return _metadata_text(source_root / path, wiki_root, path_variables)
    return _metadata_text(_path_from_wiki_metadata(raw, wiki_root, path_variables), wiki_root, path_variables)


def graphify_workspace(wiki_root: Path, scope: dict[str, Any], path_variables: dict[str, str]) -> Path | None:
    raw = (((scope.get("tooling") or {}).get("graphify") or {}).get("workspaceSubdir") or "").strip()
    if not raw:
        return None
    return _path_from_wiki_metadata(raw, wiki_root, path_variables)


def graph_shard_names(module: dict[str, Any], graph_path: str | None) -> list[str]:
    names: list[str] = []
    normalized = str(graph_path or "").replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    for index, part in enumerate(parts):
        if part == "shards" and index + 1 < len(parts):
            names.append(parts[index + 1])
            break
    module_id = str(module.get("id") or "")
    if module_id:
        names.append(module_id.replace(".", "-"))
    module_name = str(module.get("name") or module.get("logicalName") or "")
    if module_name:
        names.append(slugify(module_name))

    unique: list[str] = []
    for name in names:
        if name and name not in unique:
            unique.append(name)
    return unique


def resolve_graph_json_path(
    module: dict[str, Any],
    wiki_root: Path,
    scope: dict[str, Any],
    path_variables: dict[str, str],
) -> tuple[Path | None, list[str]]:
    graph_path = (module.get("graphify") or {}).get("graph_json_path")
    attempted: list[str] = []
    if graph_path:
        resolved = _path_from_wiki_metadata(str(graph_path), wiki_root, path_variables)
        attempted.append(str(resolved))
        if resolved.exists():
            return resolved, attempted

    workspace = graphify_workspace(wiki_root, scope, path_variables)
    if workspace is not None:
        for shard_name in graph_shard_names(module, str(graph_path or "")):
            candidate = workspace / "shards" / shard_name / "graphify-out" / "graph.json"
            attempted.append(str(candidate))
            if candidate.exists():
                return candidate, attempted
    return None, attempted


def iter_entry_points(module: dict[str, Any]) -> list[dict[str, Any]]:
    contract = module.get("technical_contract") or module.get("technicalContract") or {}
    entries: list[dict[str, Any]] = []
    for entry in as_list(contract.get("entry_points") or contract.get("entryPoints")):
        if isinstance(entry, dict):
            entries.append(entry)
        elif entry:
            entries.append({"file": str(entry)})
    return entries


def module_signal_terms(module: dict[str, Any]) -> set[str]:
    values: list[str] = [
        str(module.get("name") or ""),
        str(module.get("skill_description") or ""),
    ]
    business = module.get("business_context") or {}
    values.append(str(business.get("summary") or ""))
    values.extend(str(item) for item in as_list(business.get("terms")))
    values.extend(str(item) for item in as_list(module.get("business_tags")))

    semantic = module.get("semanticCard") or {}
    values.extend(str(item) for item in as_list(semantic.get("business_terms")))
    values.extend(str(item) for item in as_list(semantic.get("entry_symbols")))

    contract = module.get("technical_contract") or module.get("technicalContract") or {}
    values.extend(str(item) for item in as_list(contract.get("route_surface") or contract.get("routeSurface")))
    for entry in iter_entry_points(module):
        values.append(str(entry.get("file") or ""))
        values.append(str(entry.get("kind") or ""))
        values.extend(str(route) for route in as_list(entry.get("route_surface")))
        for symbol in as_list(entry.get("symbols")):
            if isinstance(symbol, dict):
                values.append(str(symbol.get("name") or ""))
            else:
                values.append(str(symbol))
    return set(top_terms(values, limit=80))


def module_route_terms(module: dict[str, Any]) -> set[str]:
    contract = module.get("technical_contract") or module.get("technicalContract") or {}
    values = [str(item) for item in as_list(contract.get("route_surface") or contract.get("routeSurface"))]
    for entry in iter_entry_points(module):
        values.extend(str(route) for route in as_list(entry.get("route_surface")))
    return set(top_terms(values, limit=80))


def module_entry_files(module: dict[str, Any]) -> list[str]:
    semantic = module.get("semanticCard") or {}
    files = [str(item) for item in as_list(semantic.get("entry_files")) if item]
    files.extend(str(entry.get("file")) for entry in iter_entry_points(module) if entry.get("file"))
    return files


def normalize_path_text(value: str) -> str:
    return str(value or "").replace("\\", "/").lower().strip()


def path_matches_any(path: str, candidates: list[str]) -> bool:
    normalized = normalize_path_text(path)
    if not normalized:
        return False
    basename = Path(normalized).name
    for candidate in candidates:
        other = normalize_path_text(candidate)
        if not other:
            continue
        if normalized.endswith(other) or other.endswith(normalized):
            return True
        if basename and basename == Path(other).name:
            return True
    return False


def score_community(
    *,
    members: list[dict[str, Any]],
    labels: list[str],
    files: list[str],
    edge_touch_count: int,
    module_terms: set[str],
    route_terms: set[str],
    entry_files: list[str],
) -> dict[str, Any]:
    semantic_keywords = top_terms(labels + files, limit=14)
    raw_keywords = set(top_terms(labels + files, limit=30, drop_noise=False))
    business_overlap = sorted(set(semantic_keywords) & module_terms)
    route_overlap = sorted(set(semantic_keywords) & route_terms)
    entry_file_overlap = sum(1 for file in set(files) if path_matches_any(file, entry_files))
    noise_terms = sorted(raw_keywords & SEMANTIC_NOISE_WORDS)
    rank_score = (
        len(members)
        + edge_touch_count * 0.25
        + min(len(business_overlap), 10) * 18
        + min(len(route_overlap), 8) * 12
        + min(entry_file_overlap, 8) * 10
        - min(len(noise_terms), 12) * 1.5
    )
    confidence = 0.55
    confidence += min(edge_touch_count, 80) / 800
    confidence += min(len(business_overlap), 8) * 0.025
    confidence += min(len(route_overlap), 6) * 0.018
    confidence += min(entry_file_overlap, 5) * 0.025
    if not business_overlap and not route_overlap and entry_file_overlap == 0:
        confidence = min(confidence, 0.61)
    return {
        "rank_score": round(rank_score, 2),
        "semantic_keywords": semantic_keywords,
        "business_term_overlap": business_overlap[:12],
        "route_term_overlap": route_overlap[:12],
        "entry_file_overlap": entry_file_overlap,
        "filtered_noise_terms": noise_terms[:12],
        "confidence": round(min(confidence, 0.88), 2),
    }


def summarize_community(module_name: str, community_id: int, title: str, quality: dict[str, Any]) -> str:
    parts = [f"Graphify community {community_id} for {module_name} centers on {title}."]
    if quality["business_term_overlap"]:
        parts.append("Module-term overlap: " + ", ".join(quality["business_term_overlap"][:8]) + ".")
    elif quality["semantic_keywords"]:
        parts.append("Structural keywords: " + ", ".join(quality["semantic_keywords"][:8]) + ".")
    if quality["route_term_overlap"]:
        parts.append("Route-surface overlap: " + ", ".join(quality["route_term_overlap"][:6]) + ".")
    if quality["entry_file_overlap"]:
        parts.append(f"Entry-file overlap count: {quality['entry_file_overlap']}.")
    if not quality["business_term_overlap"] and quality["filtered_noise_terms"]:
        parts.append("Generic platform/framework terms were filtered before ranking.")
    return " ".join(parts)


def build_module_communities(
    module: dict[str, Any],
    top_per_module: int,
    wiki_root: Path,
    path_variables: dict[str, str],
    resolved_graph_path: Path | None = None,
) -> list[dict[str, Any]]:
    graphify = module.get("graphify") or {}
    graph_path = graphify.get("graph_json_path")
    if not graph_path and resolved_graph_path is None:
        return []
    if resolved_graph_path is None:
        resolved_graph_path = _path_from_wiki_metadata(str(graph_path), wiki_root, path_variables)
    if not resolved_graph_path.exists():
        return []

    graph = load_json(resolved_graph_path)
    nodes = graph.get("nodes") or []
    edges = graph.get("links") or graph.get("edges") or []
    source_root = Path(str(module.get("resolvedPath") or "")) if module.get("resolvedPath") else None

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        community = node.get("community")
        if community is None:
            continue
        grouped[int(community)].append(node)

    edge_counter: Counter[int] = Counter()
    node_community_by_id = {str(node.get("id")): node.get("community") for node in nodes}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        for node_id in (source, target):
            community = node_community_by_id.get(node_id)
            if community is not None:
                edge_counter[int(community)] += 1

    module_id = str(module.get("id") or slugify(str(module.get("name") or "module")))
    module_terms = module_signal_terms(module)
    route_terms = module_route_terms(module)
    entry_files = module_entry_files(module)
    ranked_rows: list[tuple[float, int, list[dict[str, Any]], list[str], list[str], dict[str, Any]]] = []
    for community_id, members in grouped.items():
        labels = [node_label(node) for node in members if node_label(node)]
        files = [
            file
            for node in members
            for file in [node_file(node, wiki_root, path_variables, source_root)]
            if file
        ]
        quality = score_community(
            members=members,
            labels=labels,
            files=files,
            edge_touch_count=edge_counter[community_id],
            module_terms=module_terms,
            route_terms=route_terms,
            entry_files=entry_files,
        )
        ranked_rows.append((float(quality["rank_score"]), community_id, members, labels, files, quality))
    ranked = sorted(
        ranked_rows,
        key=lambda item: (item[0], len(item[2]), edge_counter[item[1]]),
        reverse=True,
    )[:top_per_module]

    communities: list[dict[str, Any]] = []
    for rank, (_, community_id, members, labels, files, quality) in enumerate(ranked, start=1):
        label_counts = Counter(labels)
        file_counts = Counter(files)
        top_labels = [label for label, _ in label_counts.most_common(20)]
        top_files = [file for file, _ in file_counts.most_common(12)]
        title = infer_title(top_labels, top_files)
        communities.append(
            {
                "id": f"{module_id}.community.{community_id}",
                "module_id": module_id,
                "module_name": module.get("name"),
                "solution_group": module.get("solution_group"),
                "community_id": community_id,
                "title": title,
                "summary": summarize_community(str(module.get("name") or module_id), community_id, title, quality),
                "node_count": len(members),
                "edge_touch_count": edge_counter[community_id],
                "rank": rank,
                "rank_score": quality["rank_score"],
                "core_symbols": top_labels,
                "source_files": top_files,
                "semantic_keywords": quality["semantic_keywords"],
                "business_hint": ", ".join(quality["business_term_overlap"] or quality["semantic_keywords"][:6]),
                "quality_signals": {
                    "business_term_overlap": quality["business_term_overlap"],
                    "route_term_overlap": quality["route_term_overlap"],
                    "entry_file_overlap": quality["entry_file_overlap"],
                    "filtered_noise_terms": quality["filtered_noise_terms"],
                },
                "source": "graphify",
                "source_kind": "graphify_graph_json",
                "degraded": False,
                "build_strategy": "graphify_ranked_structural_summary",
                "risk_notes": [
                    "This is deterministic navigation metadata, not source-of-truth business logic.",
                    "Use DynamicCodeProvider for detailed logic verification.",
                ]
                + (
                    ["Business overlap is low; treat this community as structural navigation only."]
                    if not quality["business_term_overlap"] and not quality["route_term_overlap"]
                    else []
                ),
                "confidence": quality["confidence"],
                "graph_json_path": _metadata_text(resolved_graph_path, wiki_root, path_variables),
            }
        )
    return communities


def infer_title(labels: list[str], files: list[str]) -> str:
    interesting = [
        label
        for label in labels
        if label
        and not label.endswith(".cs")
        and not label.startswith(".")
        and len(label) <= 80
        and split_terms(label)
    ]
    if interesting:
        return " / ".join(interesting[:3])
    if files:
        return Path(files[0]).name
    return "Untitled community"


def write_community_markdown(wiki_root: Path, community: dict[str, Any]) -> None:
    solution = slugify(str(community.get("solution_group") or "Unknown"))
    module = slugify(str(community.get("module_name") or community["module_id"]))
    path = wiki_root / "Wiki" / "03_Communities" / solution / module / f"Community {community['community_id']}.md"
    lines = [
        "---",
        f"title: {community['title']}",
        "tags:",
        "  - llm-wiki",
        "  - graphify-community",
        "status: deterministic-index",
        "---",
        "",
        f"# Community {community['community_id']} - {community['title']}",
        "",
        community["summary"],
        "",
        "## Metadata",
        "",
        f"- Module: {community['module_id']}",
        f"- Source: `{community.get('source')}`",
        f"- Degraded: `{community.get('degraded')}`",
        f"- Node count: {community['node_count']}",
        f"- Edge touch count: {community['edge_touch_count']}",
        f"- Rank score: {community.get('rank_score')}",
        f"- Confidence: {community['confidence']}",
        "",
        "## Semantic Keywords",
        "",
        *[f"- `{term}`" for term in community.get("semantic_keywords", [])[:14]],
        "",
        "## Core Symbols",
        "",
        *[f"- `{symbol}`" for symbol in community["core_symbols"][:20]],
        "",
        "## Source Files",
        "",
        *[f"- `{file}`" for file in community["source_files"][:12]],
        "",
        "## Risk Notes",
        "",
        *[f"- {note}" for note in community["risk_notes"]],
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def clear_existing_communities(wiki_root: Path) -> None:
    for path in (wiki_root / "Wiki" / "_data" / "communities").glob("*.json"):
        path.unlink()
    community_root = wiki_root / "Wiki" / "03_Communities"
    if community_root.exists():
        for path in community_root.rglob("Community *.md"):
            path.unlink()
        for path in sorted(community_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass


def build_all(wiki_root: Path, top_per_module: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_communities: list[dict[str, Any]] = []
    skipped_modules: list[dict[str, Any]] = []
    scope = _load_scope(wiki_root)
    path_variables = _load_path_variables(wiki_root)
    for module in load_modules(wiki_root):
        module_id = str(module.get("id") or slugify(str(module.get("name") or "module")))
        graph_path = (module.get("graphify") or {}).get("graph_json_path")
        try:
            resolved_graph_path, attempted_paths = resolve_graph_json_path(module, wiki_root, scope, path_variables)
        except ValueError as exc:
            skipped_modules.append({"module_id": module_id, "reason": "invalid_graph_json_path", "detail": str(exc)})
            continue
        if resolved_graph_path is None:
            reason = "graph_json_missing" if graph_path else "missing_graph_json_path"
            skipped_modules.append(
                {
                    "module_id": module_id,
                    "reason": reason,
                    "graph_json_path": str(graph_path),
                    "attempted_graph_json_paths": attempted_paths,
                }
            )
            continue
        communities = build_module_communities(module, top_per_module, wiki_root, path_variables, resolved_graph_path)
        if not communities:
            skipped_modules.append(
                {
                    "module_id": module_id,
                    "reason": "no_graphify_community_nodes",
                    "graph_json_path": str(graph_path),
                    "resolved_graph_json_path": str(resolved_graph_path),
                    "attempted_graph_json_paths": attempted_paths,
                }
            )
            continue
        all_communities.extend(communities)
    if all_communities:
        clear_existing_communities(wiki_root)
        for community in all_communities:
            out_json = wiki_root / "Wiki" / "_data" / "communities" / f"{community['id'].replace('.', '-')}.json"
            write_json(out_json, community)
            write_community_markdown(wiki_root, community)
    return all_communities, skipped_modules


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic Graphify community index")
    parser.add_argument("--wiki-root", default=".")
    parser.add_argument("--top-per-module", type=int, default=10)
    args = parser.parse_args(argv)

    wiki_root = Path(args.wiki_root).resolve()
    communities, skipped_modules = build_all(wiki_root, args.top_per_module)
    print(f"communities_written: {len(communities)}")
    modules = sorted({item["module_id"] for item in communities})
    print(f"modules_with_communities: {len(modules)}")
    print(f"modules_skipped: {len(skipped_modules)}")
    for module_id in modules[:20]:
        count = sum(1 for item in communities if item["module_id"] == module_id)
        print(f"- {module_id}: {count}")
    for skipped in skipped_modules[:20]:
        attempted = skipped.get("attempted_graph_json_paths") or []
        detail = f" attempted_graph_json_paths={attempted}" if attempted else ""
        print(f"skip_module={skipped.get('module_id')} reason={skipped.get('reason')}{detail}")
    if skipped_modules and communities:
        print("warning=some_modules_without_graphify_communities")
    if not communities:
        print("skip_reason=no_graphify_communities_available")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

'''


GRAPH_RUNTIME = r'''from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-") or "query"


def score_module(question: str, module: dict) -> int:
    q = question.lower()
    score = 0
    name = str(module.get("logicalName", "")).lower()
    if name and name in q:
        score += 10
    for term in module.get("semanticCard", {}).get("business_terms", []):
        if str(term).lower() in q:
            score += 3
    for symbol in module.get("semanticCard", {}).get("entry_symbols", []):
        symbol_l = str(symbol).lower()
        if any(part and part in q for part in re.split(r"[^a-z0-9]+", symbol_l)):
            score += 2
    for entry in module.get("technicalContract", {}).get("entryPoints", []):
        file_l = str(entry.get("file", "")).lower()
        if any(part and part in q for part in re.split(r"[^a-z0-9]+", file_l)):
            score += 1
    return score


def direct_evidence(module: dict, limit: int) -> list[dict]:
    evidence = []
    for entry in module.get("technicalContract", {}).get("entryPoints", [])[:limit]:
        symbols = entry.get("symbols", [])
        methods = entry.get("methods", [])
        evidence.append({
            "file": entry.get("file"),
            "kind": entry.get("entryKind", "source_file"),
            "symbols": [symbol.get("name") for symbol in symbols[:10]],
            "methods": [method.get("name") for method in methods[:10]],
            "routes": entry.get("routes", [])[:10],
            "source": "static_entry_seed",
        })
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki-root", default=".")
    parser.add_argument("--question", required=True)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--extract-limit", type=int, default=4)
    args = parser.parse_args()
    root = Path(args.wiki_root).resolve()
    modules = []
    for module_file in (root / "Wiki" / "_data" / "modules").glob("*.json"):
        module = json.loads(module_file.read_text(encoding="utf-8"))
        module["_path"] = str(module_file)
        module["_score"] = score_module(args.question, module)
        modules.append(module)
    modules.sort(key=lambda item: item["_score"], reverse=True)
    selected = modules[: args.top]
    direct = direct_evidence(selected[0], args.extract_limit) if args.extract and selected else []
    status = "strong" if selected and selected[0]["_score"] > 0 else "partial" if selected else "weak"
    run = {
        "question": args.question,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "selected_modules": [{"module": m.get("logicalName"), "score": m.get("_score"), "path": m.get("_path")} for m in selected],
        "rejected_modules": [{"module": m.get("logicalName"), "score": m.get("_score"), "path": m.get("_path")} for m in modules[args.top: args.top + 10]],
        "semantic": {
            "intake": {"question_type": "static_smoke", "terms": re.findall(r"[A-Za-z0-9_]+", args.question)[:20]},
            "routing": {
                "ambiguity": "low" if status == "strong" else "unknown",
                "needs_fixed_matrix": False,
                "score_source": "module name + business terms + entry symbols + route surface",
            },
            "evidence_sufficiency": {
                "status": status,
                "can_answer": bool(direct) or status == "strong",
                "next_step": "review intake/overlay facts or run backfill if implementation evidence is insufficient",
            },
        },
        "extraction_plan": {
            "source": "static_entry_seed" if direct else "module_metadata_only",
            "fallback_reason": None if direct else "no entry files available for extraction",
        },
        "synthesis_inputs": {"direct_evidence": direct},
    }
    out_dir = root / "Wiki" / "_data" / "query_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"query_{now_stamp()}_{slug(args.question)[:60]}.json"
    out_path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"query run: {out_path}")
    print(f"verdict: {status}")
    return 0 if selected else 2


if __name__ == "__main__":
    raise SystemExit(main())
'''


EVAL_QUERIES = r'''from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki-root", default=".")
    parser.add_argument("--runtime", default="graph")
    args = parser.parse_args()
    root = Path(args.wiki_root).resolve()
    modules = list((root / "Wiki" / "_data" / "modules").glob("*.json"))
    communities = list((root / "Wiki" / "_data" / "communities").glob("*.json"))
    result = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "runtime": args.runtime,
        "moduleCount": len(modules),
        "communityCount": len(communities),
        "passed": bool(modules),
    }
    out_dir = root / "Wiki" / "_eval" / "eval_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"eval_{args.runtime}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"eval run: {out_path}")
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
'''


DIFF_WIKI = r'''from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki-root", default=".")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--target-ref", default="HEAD")
    parser.add_argument("--accept-baseline", action="store_true")
    args = parser.parse_args()
    wiki_root = Path(args.wiki_root).resolve()
    repo_root = Path(args.repo_root).resolve()
    state_path = wiki_root / args.state
    state = {}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    target = git(repo_root, "rev-parse", args.target_ref)
    if target.returncode != 0:
        print(target.stderr.strip())
        return 2
    target_commit = target.stdout.strip()
    baseline = args.baseline or state.get("last_synced_commit")
    changed = []
    if baseline:
        diff = git(repo_root, "diff", "--name-only", baseline, target_commit)
        if diff.returncode == 0:
            changed = [line for line in diff.stdout.splitlines() if line.strip()]
    else:
        listing = git(repo_root, "ls-tree", "-r", "--name-only", target_commit)
        if listing.returncode == 0:
            changed = [line for line in listing.stdout.splitlines() if line.strip()]
    report = {
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "repo_root": str(repo_root),
        "baseline": baseline,
        "target_ref": args.target_ref,
        "target_commit": target_commit,
        "changed_file_count": len(changed),
        "changed_files": changed[:500],
        "status": "completed-noop" if baseline and len(changed) == 0 else "diff-ready",
    }
    report_dir = wiki_root / "Wiki" / "_meta" / "master_sync_runs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"diff_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.accept_baseline:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "repo_root": str(repo_root),
            "last_synced_commit": target_commit,
            "updatedAt": report["generatedAt"],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"diff report: {report_path}")
    print(f"changed files: {len(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def build_scope(project_name: str | None, repo_path: str | None) -> dict:
    scope = {
        "version": 1,
        "stage": "bootstrap",
        "workspaceRoot": ".",
        "policy": {
            "sourceOfTruth": "json",
            "scopeLocked": True,
            "allowOnlyListedRepos": True,
        },
        "inventory": {
            "childDepth": 1,
            "markerMaxDepth": 2,
            "markerFiles": ["package.json", "settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts"],
            "markerExtensions": [".sln", ".csproj", ".vbproj"],
            "skipDirectoryNames": sorted(SKIP_DIRS),
        },
        "dataFiles": {
            "inventoryJson": "Wiki/_data/scope.inventory.json",
            "toolingJson": "Wiki/_data/tooling.status.json",
            "systemIndexJson": "Wiki/_data/system.index.json",
        },
        "renderFiles": {
            "inventoryMarkdown": "Wiki/00_Scope_Inventory.md",
            "systemIndexMarkdown": "Wiki/00_System_Index.md",
            "wikiReportMarkdown": "Wiki/wiki_report.md",
        },
        "repos": [],
    }
    if project_name and repo_path:
        scope["repos"].append({
            "logicalName": project_name,
            "actualRoot": repo_path,
            "include": True,
            "reason": "Initial repo seeded by llm-wiki-bootstrap.",
            "targets": [{
                "logicalName": project_name,
                "actualPath": repo_path,
                "type": "project-root",
                "include": True,
                "reason": "Initial whole-repo module.",
            }],
        })
    return scope


def create_scaffold(args: argparse.Namespace) -> list[str]:
    wiki_root = Path(args.wiki_root).resolve()
    repo_path = str(Path(args.repo_path).resolve()) if args.repo_path else None
    project_name = args.project_name or (Path(repo_path).name if repo_path else None)
    created: list[str] = []

    dirs = [
        "Wiki/_data/modules",
        "Wiki/_data/symbols",
        "Wiki/_data/communities",
        "Wiki/_data/query_runs",
        "Wiki/_meta/repo_sync",
        "Wiki/_meta/master_sync_runs",
        "Wiki/01_Modules",
        "Wiki/02_Symbols",
        "Wiki/03_Communities",
        "intake",
    ]
    for rel in dirs:
        path = wiki_root / rel
        path.mkdir(parents=True, exist_ok=True)
        created.append(str(path))

    files = {
        "requirements.txt": "graphifyy>=0.4.10,<0.9\nlanggraph>=0.2\ntree-sitter>=0.21\ntree-sitter-c-sharp>=0.21\n",
        "README.md": "# LLM Wiki\n\nBootstrap-created LLM Wiki environment. Run module onboarding next to strengthen metadata and evidence.\n",
    }
    for rel, content in files.items():
        if write_text(wiki_root / rel, content, overwrite=args.overwrite_scripts):
            created.append(str(wiki_root / rel))

    scope_path = wiki_root / "wiki.scope.json"
    if not scope_path.exists() or args.overwrite_scope:
        write_json(scope_path, build_scope(project_name, repo_path), overwrite=True)
        created.append(str(scope_path))
    elif repo_path and project_name:
        scope = json.loads(scope_path.read_text(encoding="utf-8"))
        repos = scope.setdefault("repos", [])
        exists = any(r.get("logicalName") == project_name or r.get("actualRoot") == repo_path for r in repos)
        if not exists:
            repos.append(build_scope(project_name, repo_path)["repos"][0])
            write_json(scope_path, scope, overwrite=True)
            created.append(str(scope_path))

    if project_name and repo_path:
        intake = wiki_root / "intake" / f"{safe_slug(project_name)}.md"
        intake_text = (
            f"# {project_name} Intake\n\n"
            f"- repo path: `{repo_path}`\n"
            f"- wiki root: `{wiki_root}`\n"
            f"- python command: `{args.python_command}`\n"
            f"- created: `{now_iso()}`\n\n"
            "## Notes\n\n"
            "- Bootstrap created the first environment. Run module onboarding to strengthen semantic metadata.\n"
        )
        if write_text(intake, intake_text, overwrite=False):
            created.append(str(intake))

    return created


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki-root", required=True)
    parser.add_argument("--repo-path")
    parser.add_argument("--project-name")
    parser.add_argument("--python-command", default=sys.executable)
    parser.add_argument("--overwrite-scripts", action="store_true")
    parser.add_argument("--overwrite-scope", action="store_true")
    args = parser.parse_args()

    if args.repo_path and not Path(args.repo_path).exists():
        print(f"repo path does not exist: {args.repo_path}", file=sys.stderr)
        return 2

    created = create_scaffold(args)
    print("LLM Wiki bootstrap complete")
    print(f"wiki root: {Path(args.wiki_root).resolve()}")
    if args.repo_path:
        print(f"repo path: {Path(args.repo_path).resolve()}")
    print(f"python command: {args.python_command}")
    print("created or updated:")
    for item in created:
        print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
