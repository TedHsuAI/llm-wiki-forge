from __future__ import annotations

import argparse
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .io import load_json, load_modules, slugify, write_json


def node_label(node: dict[str, Any]) -> str:
    return str(node.get("label") or node.get("id") or "")


def _load_path_variables(wiki_root: Path) -> dict[str, str]:
    scope_path = wiki_root / "wiki.scope.json"
    if not scope_path.exists():
        return {}
    scope = load_json(scope_path)
    return {str(key): str(value) for key, value in (scope.get("pathVariables") or {}).items()}


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
        return os.path.relpath(path, base_dir).replace("\\", "/")
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


def build_module_communities(
    module: dict[str, Any],
    top_per_module: int,
    wiki_root: Path,
    path_variables: dict[str, str],
) -> list[dict[str, Any]]:
    graphify = module.get("graphify") or {}
    graph_path = graphify.get("graph_json_path")
    if not graph_path:
        return []
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

    ranked = sorted(
        grouped.items(),
        key=lambda item: (len(item[1]), edge_counter[item[0]]),
        reverse=True,
    )[:top_per_module]

    module_id = str(module.get("id") or slugify(str(module.get("name") or "module")))
    communities: list[dict[str, Any]] = []
    for community_id, members in ranked:
        labels = [node_label(node) for node in members if node_label(node)]
        files = [
            file
            for node in members
            for file in [node_file(node, wiki_root, path_variables, source_root)]
            if file
        ]
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
                "summary": (
                    f"Deterministic Graphify community index for {module.get('name')} "
                    f"community {community_id}. LLM semantic summary is not generated yet."
                ),
                "node_count": len(members),
                "edge_touch_count": edge_counter[community_id],
                "core_symbols": top_labels,
                "source_files": top_files,
                "business_hint": "",
                "risk_notes": [
                    "This is deterministic navigation metadata, not source-of-truth business logic.",
                    "Use DynamicCodeProvider for detailed logic verification.",
                ],
                "confidence": 0.62,
                "graph_json_path": _metadata_text(resolved_graph_path, wiki_root, path_variables),
            }
        )
    return communities


def infer_title(labels: list[str], files: list[str]) -> str:
    interesting = [
        label
        for label in labels
        if label and not label.endswith(".cs") and not label.startswith(".") and len(label) <= 80
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
        f"- Node count: {community['node_count']}",
        f"- Edge touch count: {community['edge_touch_count']}",
        f"- Confidence: {community['confidence']}",
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


def build_all(wiki_root: Path, top_per_module: int) -> list[dict[str, Any]]:
    all_communities: list[dict[str, Any]] = []
    path_variables = _load_path_variables(wiki_root)
    for module in load_modules(wiki_root):
        communities = build_module_communities(module, top_per_module, wiki_root, path_variables)
        all_communities.extend(communities)
    if all_communities:
        clear_existing_communities(wiki_root)
        for community in all_communities:
            out_json = wiki_root / "Wiki" / "_data" / "communities" / f"{community['id'].replace('.', '-')}.json"
            write_json(out_json, community)
            write_community_markdown(wiki_root, community)
    return all_communities


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic Graphify community index")
    parser.add_argument("--wiki-root", default=".")
    parser.add_argument("--top-per-module", type=int, default=10)
    args = parser.parse_args(argv)

    wiki_root = Path(args.wiki_root).resolve()
    communities = build_all(wiki_root, args.top_per_module)
    print(f"communities_written: {len(communities)}")
    modules = sorted({item["module_id"] for item in communities})
    print(f"modules_with_communities: {len(modules)}")
    for module_id in modules[:20]:
        count = sum(1 for item in communities if item["module_id"] == module_id)
        print(f"- {module_id}: {count}")
    if not communities:
        print("skip_reason=no_graphify_communities_available")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
