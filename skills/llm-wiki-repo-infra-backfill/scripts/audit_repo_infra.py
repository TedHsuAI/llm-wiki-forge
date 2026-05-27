#!/usr/bin/env python3
"""Lightweight LLM Wiki per-repo infrastructure audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


NOISE_TERMS = (
    "jquery",
    "sizzle",
    "bootstrap",
    ".min.js",
    "node_modules",
    "/bin/",
    "\\bin\\",
    "/obj/",
    "\\obj\\",
    "packages/",
    "packages\\",
)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def load_json(path: Path) -> Any:
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError:
        return None


def json_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.json") if p.is_file())


def find_matches(root: Path, needles: list[str]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for path in json_files(root):
        text = read_text(path)
        haystack = text.lower()
        if any(n in haystack for n in needles):
            matches.append(
                {
                    "path": str(path),
                    "size": path.stat().st_size,
                    "noise_hits": sorted(term for term in NOISE_TERMS if term in haystack),
                }
            )
    return matches


def newest_query_runs(root: Path, needles: list[str], limit: int) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    paths = sorted((p for p in root.rglob("*.json") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    result: list[dict[str, Any]] = []
    for path in paths:
        text = read_text(path)
        haystack = text.lower()
        if any(n in haystack for n in needles):
            data = load_json(path)
            keys = sorted(data.keys()) if isinstance(data, dict) else []
            result.append({"path": str(path), "keys": keys[:30], "size": path.stat().st_size})
        if len(result) >= limit:
            break
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit one repo/module in an LLM Wiki.")
    parser.add_argument("--wiki-root", required=True, help="Path to the LLM Wiki root.")
    parser.add_argument("--repo", required=True, help="Repo logical name or path fragment.")
    parser.add_argument("--limit", type=int, default=5, help="Newest matching query runs to list.")
    args = parser.parse_args()

    wiki_root = Path(args.wiki_root).resolve()
    repo = args.repo.strip()
    needles = [repo.lower()]
    if "\\" in repo or "/" in repo:
        needles.extend(part.lower() for part in Path(repo).parts if len(part) > 2)

    data_root = wiki_root / "Wiki" / "_data"
    scope_text = read_text(wiki_root / "wiki.scope.json").lower()
    inventory_text = read_text(data_root / "scope.inventory.json").lower()

    modules = find_matches(data_root / "modules", needles)
    symbols = find_matches(data_root / "symbols", needles)
    communities = find_matches(data_root / "communities", needles)
    query_runs = newest_query_runs(data_root / "query_runs", needles, args.limit)

    noise_files = [m for m in communities if m["noise_hits"]]
    warnings: list[str] = []
    if not any(n in scope_text for n in needles):
        warnings.append("repo not found in wiki.scope.json")
    if not any(n in inventory_text for n in needles):
        warnings.append("repo not found in scope.inventory.json")
    if not modules:
        warnings.append("no matching module metadata")
    if not symbols:
        warnings.append("no matching symbol metadata; verify entry_points or overlay seeds")
    if noise_files:
        warnings.append("community matches include vendor/generated noise")
    if not query_runs:
        warnings.append("no matching query runs found")

    summary = {
        "wiki_root": str(wiki_root),
        "repo": repo,
        "counts": {
            "modules": len(modules),
            "symbols": len(symbols),
            "communities": len(communities),
            "community_noise_files": len(noise_files),
            "query_runs": len(query_runs),
        },
        "modules": modules[:20],
        "symbols": symbols[:20],
        "communities": communities[:20],
        "query_runs": query_runs,
        "warnings": warnings,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
