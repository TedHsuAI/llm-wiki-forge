#!/usr/bin/env python3
"""Summarize LLM Wiki query runs for routing and extraction comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return None


def find_key(obj: Any, names: set[str]) -> Any:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() in names:
                return value
        for value in obj.values():
            found = find_key(value, names)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_key(value, names)
            if found is not None:
                return found
    return None


def compact(value: Any, limit: int = 800) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        text = str(value)
        return text if len(text) <= limit else text[:limit] + "...<truncated>"
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def score_for_repo(data: Any, repo: str) -> Any:
    repo_l = repo.lower()
    candidates = find_key(data, {"selected_modules", "module_scores", "scores", "routing_scores", "routes"})
    if isinstance(candidates, dict):
        for key, value in candidates.items():
            if repo_l in str(key).lower():
                return value
    if isinstance(candidates, list):
        for item in candidates:
            text = json.dumps(item, ensure_ascii=False, default=str).lower()
            if repo_l in text:
                return item
    return candidates


def summarize_run(path: Path, repo: str) -> dict[str, Any]:
    data = load_json(path)
    if data is None:
        return {"path": str(path), "error": "invalid-json"}

    return {
        "path": str(path),
        "question": compact(find_key(data, {"question", "user_question", "query"}), 240),
        "repo_score_or_route": compact(score_for_repo(data, repo), 1000),
        "selected_modules": compact(find_key(data, {"selected_modules"}), 1000),
        "rejected_modules": compact(find_key(data, {"rejected_modules"}), 1000),
        "extraction_plan": compact(find_key(data, {"extraction_plan", "plan"}), 1200),
        "plan_source": compact(find_key(data, {"plan_source", "extraction_plan_source", "source"}), 300),
        "direct_evidence": compact(find_key(data, {"direct_evidence", "evidence", "evidence_items"}), 1200),
        "fallback_reason": compact(find_key(data, {"fallback_reason", "skip_reason", "reason"}), 400),
        "convergence": compact(find_key(data, {"convergence", "finalize", "challenge_findings"}), 800),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare recent LLM Wiki query runs for one repo.")
    parser.add_argument("--wiki-root", required=True, help="Path to LLM Wiki root.")
    parser.add_argument("--repo", required=True, help="Repo/module name or identifying fragment.")
    parser.add_argument("--limit", type=int, default=8, help="Maximum matching runs to summarize.")
    parser.add_argument("--run", action="append", default=[], help="Specific query-run JSON path. Can repeat.")
    args = parser.parse_args()

    repo_l = args.repo.lower()
    paths: list[Path] = []
    if args.run:
        paths = [Path(p) for p in args.run]
    else:
        query_root = Path(args.wiki_root) / "Wiki" / "_data" / "query_runs"
        if query_root.exists():
            all_runs = sorted(
                (p for p in query_root.rglob("*.json") if p.is_file()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for path in all_runs:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
                if repo_l in text or repo_l in path.name.lower():
                    paths.append(path)
                if len(paths) >= args.limit:
                    break

    output = {
        "wiki_root": str(Path(args.wiki_root).resolve()),
        "repo": args.repo,
        "count": len(paths),
        "runs": [summarize_run(path, args.repo) for path in paths],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if paths else 1


if __name__ == "__main__":
    raise SystemExit(main())
