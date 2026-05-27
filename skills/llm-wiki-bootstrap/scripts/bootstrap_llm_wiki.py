#!/usr/bin/env python3
"""Create a portable first-run LLM Wiki scaffold.

The generated scaffold intentionally uses only the Python standard library.
It is a starter toolkit: teams can replace or extend the scripts later while
keeping the same wiki.scope.json and Wiki folder contract.
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
import json
import os
from datetime import datetime, timezone
from pathlib import Path


SKIP_DIRS = {".git", ".vs", "bin", "build", "coverage", "obj", "node_modules", "packages", "TestResults"}


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


def discover_source(path: Path) -> dict:
    if not path.exists():
        return {"exists": False, "projectFiles": [], "solutionFiles": [], "csharpFiles": 0}
    project_files = []
    solution_files = []
    csharp_count = 0
    for item in path.rglob("*"):
        if should_skip(item):
            continue
        if item.is_file() and item.suffix.lower() == ".cs":
            csharp_count += 1
        elif item.is_file() and item.suffix.lower() == ".csproj":
            project_files.append(str(item))
        elif item.is_file() and item.suffix.lower() == ".sln":
            solution_files.append(str(item))
    return {
        "exists": True,
        "projectFiles": project_files,
        "solutionFiles": solution_files,
        "csharpFiles": csharp_count,
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


def build_inventory(root: Path) -> dict:
    scope = load_scope(root)
    items = []
    for repo, target, raw_path, resolved in iter_targets(root, scope):
        probe = discover_source(resolved)
        items.append({
            "repo": repo.get("logicalName"),
            "logicalName": target.get("logicalName") or repo.get("logicalName"),
            "actualPath": raw_path,
            "resolvedPath": str(resolved),
            "type": target.get("type", "project-root"),
            "exists": probe["exists"],
            "projectFiles": probe["projectFiles"],
            "solutionFiles": probe["solutionFiles"],
            "csharpFiles": probe["csharpFiles"],
        })
    return {"generatedAt": now_iso(), "items": items}


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
            f"- csharp files: `{item['csharpFiles']}`",
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
    (root / "Wiki" / "_data" / "tooling.status.json").write_text(json.dumps({"generatedAt": now_iso(), "status": "bootstrap-minimal"}, indent=2) + "\n", encoding="utf-8")
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
import re
from datetime import datetime, timezone
from pathlib import Path

from scripts.update_wiki import SKIP_DIRS, build_inventory


ENTRY_HINTS = ("Controller", "Service", "Repository", "Repo", "Job", "Handler", "Filter", "Worker", "HostedService", "BackgroundService", "Program", "Startup")
NOISE_WORDS = {
    "abstract", "base", "common", "config", "configuration", "constant", "constants", "controller",
    "data", "default", "dto", "entity", "enum", "exception", "extension", "extensions", "helper",
    "helpers", "hosted", "interface", "internal", "job", "manager", "model", "models", "option",
    "options", "program", "provider", "repo", "repository", "request", "response", "service",
    "settings", "startup", "system", "task", "test", "tests", "type", "utils", "worker",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-") or "module"


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def split_words(value: str) -> list[str]:
    words: list[str] = []
    for chunk in re.split(r"[^A-Za-z0-9]+", value):
        if not chunk:
            continue
        parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", chunk).split()
        words.extend(part.lower() for part in parts if len(part) >= 3)
    return [word for word in words if word not in NOISE_WORDS]


def classify_entry(path: Path, symbols: list[dict]) -> str:
    lowered = str(path).lower()
    names = " ".join(str(symbol.get("name", "")) for symbol in symbols).lower()
    combined = lowered + " " + names
    if "controller" in combined:
        return "api_controller"
    if "hostedservice" in combined or "backgroundservice" in combined or "worker" in combined:
        return "background_worker"
    if "handler" in combined:
        return "handler"
    if "repository" in combined or lowered.endswith("repo.cs"):
        return "repository"
    if "service" in combined:
        return "service"
    if path.name in {"Program.cs", "Startup.cs"}:
        return "application_bootstrap"
    return "source_file"


def extract_methods(text: str) -> list[dict]:
    methods = []
    pattern = re.compile(
        r"(?:public|private|protected|internal|static|async|virtual|override|sealed|partial|\s)+"
        r"[\w<>\[\],\s?]+?\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        name = match.group(1)
        if name in {"if", "for", "foreach", "while", "switch", "catch", "using", "lock"}:
            continue
        methods.append({"name": name})
    return methods[:40]


def extract_routes(text: str) -> list[str]:
    routes = []
    for match in re.finditer(r"\[(?:Route|HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch)\s*(?:\(\s*\"([^\"]+)\"\s*\))?", text):
        routes.append(match.group(1) or match.group(0).strip("[]"))
    return routes[:20]


def scan_csharp(root: Path, limit: int = 800) -> list[dict]:
    entries = []
    if not root.exists():
        return entries
    for path in root.rglob("*.cs"):
        if should_skip(path):
            continue
        rel = path.relative_to(root)
        text = path.read_text(encoding="utf-8", errors="ignore")
        symbols = []
        for match in re.finditer(r"\b(class|interface|record|struct|enum)\s+([A-Za-z_][A-Za-z0-9_]*)", text):
            symbols.append({"kind": match.group(1), "name": match.group(2)})
        usings = sorted(set(re.findall(r"^\s*using\s+([A-Za-z0-9_.]+)\s*;", text, flags=re.MULTILINE)))[:40]
        methods = extract_methods(text)
        routes = extract_routes(text)
        score = sum(2 for hint in ENTRY_HINTS if hint.lower() in path.name.lower())
        score += 3 if routes else 0
        score += 1 if methods else 0
        kind = classify_entry(rel, symbols)
        entries.append({
            "file": str(rel),
            "symbols": symbols[:30],
            "methods": methods,
            "routes": routes,
            "usings": usings,
            "entryKind": kind,
            "entryScore": score,
        })
        if len(entries) >= limit:
            break
    return entries


def summarize_terms(name: str, entries: list[dict]) -> list[str]:
    counter: collections.Counter[str] = collections.Counter(split_words(name))
    for entry in entries:
        counter.update(split_words(entry.get("file", "")))
        for symbol in entry.get("symbols", []):
            counter.update(split_words(str(symbol.get("name", ""))))
        for method in entry.get("methods", []):
            counter.update(split_words(str(method.get("name", ""))))
    return [word for word, _ in counter.most_common(30)]


def summarize_dependencies(entries: list[dict]) -> list[str]:
    counter: collections.Counter[str] = collections.Counter()
    for entry in entries:
        for using in entry.get("usings", []):
            if using.startswith(("System", "Microsoft", "Newtonsoft")):
                continue
            counter[using] += 1
    return [name for name, _ in counter.most_common(30)]


def symbol_refs(entries: list[dict], limit: int = 40) -> list[str]:
    refs = []
    for entry in entries:
        for symbol in entry.get("symbols", []):
            refs.append(f"{entry['file']} :: {symbol.get('name')}")
            if len(refs) >= limit:
                return refs
    return refs


def render_module(module: dict) -> str:
    lines = [
        f"# {module['logicalName']}",
        "",
        f"Source path: `{module['sourcePath']}`",
        "",
        "## Responsibility",
        "",
        *[f"- {item}" for item in module["semanticCard"]["owns"]],
        "",
        "## Boundaries",
        "",
        *[f"- {item}" for item in module["semanticCard"]["not_owns"]],
        "",
        "## Business Terms",
        "",
        ", ".join(module["semanticCard"]["business_terms"][:30]) or "No terms inferred.",
        "",
        "## Entry Points",
        "",
    ]
    for entry in module["technicalContract"]["entryPoints"][:20]:
        symbol_names = ", ".join(symbol.get("name", "") for symbol in entry.get("symbols", [])[:5])
        suffix = f" — {symbol_names}" if symbol_names else ""
        lines.append(f"- `{entry['file']}` ({entry.get('entryKind', 'source_file')}){suffix}")
    if not module["technicalContract"]["entryPoints"]:
        lines.append("- No C# entry files found yet.")
    lines.extend([
        "",
        "## Dependencies",
        "",
        *[f"- `{item}`" for item in module["technicalContract"].get("dependencies", [])[:30]],
        "",
        "## Extraction Seeds",
        "",
        *[f"- `{item}`" for item in module["semanticCard"].get("entry_symbols", [])[:40]],
        "",
        "## Confidence And Risk",
        "",
        f"- confidence: `{module['confidence']}`",
        *[f"- {item}" for item in module.get("riskNotes", [])],
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki-root", default=".")
    args = parser.parse_args()
    root = Path(args.wiki_root).resolve()
    inventory = build_inventory(root)
    data_modules = root / "Wiki" / "_data" / "modules"
    data_symbols = root / "Wiki" / "_data" / "symbols"
    modules_md = root / "Wiki" / "01_Modules"
    symbols_md = root / "Wiki" / "02_Symbols"
    for folder in (data_modules, data_symbols, modules_md, symbols_md):
        folder.mkdir(parents=True, exist_ok=True)
    built = 0
    for item in inventory["items"]:
        if not item.get("exists"):
            continue
        name = item["logicalName"]
        source = Path(item["resolvedPath"])
        csharp = scan_csharp(source)
        entry_points = [entry for entry in csharp if entry["entryScore"] > 0] or csharp[:20]
        business_terms = summarize_terms(name, csharp)
        dependencies = summarize_dependencies(csharp)
        entry_symbols = symbol_refs(entry_points)
        confidence = "static-first-pass" if csharp else "empty-or-non-csharp"
        module = {
            "logicalName": name,
            "sourcePath": item["actualPath"],
            "resolvedPath": item["resolvedPath"],
            "generatedAt": now_iso(),
            "semanticCard": {
                "owns": [
                    f"{name} owns the source tree at {item['actualPath']}.",
                    f"Static scan found {len(csharp)} C# files and {len(entry_points)} likely entry files.",
                ],
                "not_owns": [
                    "Generated/vendor/build output excluded by scope filters.",
                    "Responsibilities not visible in source names require intake or overlay refinement.",
                ],
                "business_terms": business_terms or [name],
                "misleading_terms": ["bootstrap-only", "vendor", "generated"],
                "confused_modules": [],
                "entry_symbols": entry_symbols,
                "entry_files": [entry["file"] for entry in entry_points[:40]],
                "fast_path_questions": [
                    f"What is the main responsibility of {name}?",
                    f"What are the main entry points of {name}?",
                ],
            },
            "technicalContract": {
                "entryPoints": entry_points,
                "routeSurface": [entry["file"] for entry in entry_points[:20]],
                "dependencies": dependencies,
                "projectFiles": item.get("projectFiles", []),
                "solutionFiles": item.get("solutionFiles", []),
            },
            "riskNotes": [
                "This artifact is generated by static source scanning; review intake/overlay facts for business vocabulary.",
                "Method bodies are not summarized yet; query runtime should extract listed files before broad search.",
            ],
            "confidence": confidence,
        }
        module_slug = slug(name)
        (data_modules / f"{module_slug}.json").write_text(json.dumps(module, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        module_dir = modules_md / module_slug
        module_dir.mkdir(parents=True, exist_ok=True)
        (module_dir / f"{module_slug}.md").write_text(render_module(module), encoding="utf-8", newline="\n")
        symbols = {"module": name, "generatedAt": now_iso(), "symbols": csharp}
        (data_symbols / f"{module_slug}.json").write_text(json.dumps(symbols, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        symbol_dir = symbols_md / module_slug
        symbol_dir.mkdir(parents=True, exist_ok=True)
        (symbol_dir / "_index.md").write_text(f"# {name} Symbols\n\nBootstrap symbol seed count: {len(csharp)}\n", encoding="utf-8", newline="\n")
        built += 1
    print(f"modules built: {built}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


COMMUNITY_BUILDER = r'''from __future__ import annotations

import argparse
import collections
import json
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def group_entries(entries: list[dict]) -> list[dict]:
    groups: collections.defaultdict[str, list[dict]] = collections.defaultdict(list)
    for entry in entries:
        groups[entry.get("entryKind", "source_file")].append(entry)
    result = []
    for kind, items in sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        result.append({
            "name": kind,
            "count": len(items),
            "files": [item.get("file") for item in items[:15]],
            "symbols": [
                f"{item.get('file')} :: {symbol.get('name')}"
                for item in items[:15]
                for symbol in item.get("symbols", [])[:3]
            ][:30],
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki-root", default=".")
    parser.add_argument("--top-per-module", type=int, default=10)
    args = parser.parse_args()
    root = Path(args.wiki_root).resolve()
    out = root / "Wiki" / "_data" / "communities"
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    for module_file in (root / "Wiki" / "_data" / "modules").glob("*.json"):
        module = json.loads(module_file.read_text(encoding="utf-8"))
        entries = module.get("technicalContract", {}).get("entryPoints", [])[: args.top_per_module]
        all_entries = module.get("technicalContract", {}).get("entryPoints", [])
        community = {
            "module": module.get("logicalName"),
            "generatedAt": now_iso(),
            "source": "static_module_derived",
            "degraded": True,
            "reason": "Graph backend is not bundled; community fallback is derived from static module metadata.",
            "terms": module.get("semanticCard", {}).get("business_terms", [])[:30],
            "dependencies": module.get("technicalContract", {}).get("dependencies", [])[:30],
            "clusters": group_entries(all_entries),
            "items": [
                {
                    "file": entry.get("file"),
                    "kind": entry.get("entryKind", "entry_point"),
                    "symbols": [symbol.get("name") for symbol in entry.get("symbols", [])[:10]],
                }
                for entry in entries
            ],
        }
        (out / module_file.name).write_text(json.dumps(community, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        count += 1
    print(f"communities built: {count}")
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
            "markerFiles": ["package.json"],
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
        "scripts/query_runtime",
        "scripts/repo_sync",
    ]
    for rel in dirs:
        path = wiki_root / rel
        path.mkdir(parents=True, exist_ok=True)
        created.append(str(path))

    files = {
        "scripts/__init__.py": "",
        "scripts/query_runtime/__init__.py": "",
        "scripts/repo_sync/__init__.py": "",
        "scripts/update_wiki.py": UPDATE_WIKI,
        "scripts/generate_module_wiki.py": GENERATE_MODULE_WIKI,
        "scripts/query_runtime/community_builder.py": COMMUNITY_BUILDER,
        "scripts/query_runtime/graph_runtime.py": GRAPH_RUNTIME,
        "scripts/query_runtime/eval_queries.py": EVAL_QUERIES,
        "scripts/repo_sync/diff_wiki.py": DIFF_WIKI,
        "requirements.txt": "# Bootstrap scaffold uses Python standard library only.\n# Add toolkit-specific dependencies here when you extend the pipeline.\n",
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
