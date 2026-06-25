from __future__ import annotations

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
    "ios",
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
    "swift",
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
    "xcode",
    "xml",
}
CODE_FILE_SUFFIXES = {".cs", ".kt", ".kts", ".java", ".swift", ".m", ".mm", ".h"}


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
        and Path(label).suffix.lower() not in CODE_FILE_SUFFIXES
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
