from __future__ import annotations

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
    if platform == "csharp":
        active_roots = [Path(project).resolve().parent for project in item.get("projectFiles") or [] if Path(project).exists()]
        enforce_scope = item.get("projectScopeSource") in {"solution_filter", "solution"} and bool(active_roots)
        files = []
        for path in scan_root.rglob("*.cs"):
            if should_skip(path):
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


def extract_retrofit_surface(text: str) -> list[str]:
    surface = []
    for match in re.finditer(r"@(GET|POST|PUT|DELETE|PATCH)\s*\(\s*\"([^\"]+)\"", text):
        surface.append(f"{match.group(1)} {match.group(2)}")
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
    for path in files:
        rel = path.relative_to(scan_root)
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        file_symbols = extract_symbols(text, path.suffix.lower())
        methods = extract_methods(text, path.suffix.lower())
        entry_kind = classify_entry(rel, text, file_symbols, platform)
        routes = extract_csharp_routes(text) if platform == "csharp" else extract_retrofit_surface(text)
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
    return [word for word, _ in counter.most_common(40)]


def discover_android_surfaces(source: Path) -> dict[str, Any]:
    scan_root = source.parent if source.is_file() else source
    gradle_files = [
        str(path.relative_to(scan_root)).replace("\\", "/")
        for name in ANDROID_BUILD_FILES
        for path in scan_root.rglob(name)
        if not should_skip(path)
    ][:80]
    manifests = []
    manifest_components: list[str] = []
    for manifest in scan_root.rglob("AndroidManifest.xml"):
        if should_skip(manifest):
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
    android = discover_android_surfaces(source) if platform == "android" and source.exists() else {}
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
        lines.append(f"- `{entry.get('file')}` ({entry.get('kind')}){suffix}")
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
