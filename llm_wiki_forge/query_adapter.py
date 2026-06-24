#!/usr/bin/env python3
"""Read-only Hermes tools for the local LLM Wiki query runtime."""

from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_wiki_forge.runtime import run_packaged_module


DEFAULT_WIKI_ROOT = "/home/tedhsu/.hermes/data/llm-wiki"
DEFAULT_PYTHON = sys.executable
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_DETAIL = "compact"
COMPACT_DIRECT_EVIDENCE_LIMIT = 5
COMPACT_SOURCE_MATCH_LIMIT = 5
COMPACT_SNIPPET_CHARS = 500
COMPACT_MATCH_CHARS = 300
RECENT_QUERY_RUN_LIMIT = 200
DEFAULT_REUSE_DAYS = 7
DEFAULT_DOMAIN_ROOT = "/home/tedhsu/DispatchRawdata"
VALIDATION_INDEX = "Wiki/_data/query_cache_validations.json"
FRESHNESS_KEYWORDS = (
    "最新",
    "剛改",
    "剛剛",
    "現在",
    "目前",
    "master",
    "更新後",
    "部署後",
    "commit",
    "git",
)
RUNTIME_MODULES = {
    "query": "scripts.query_runtime.query_orchestrator",
    "source-search": "scripts.query_runtime.source_search",
}


def tool_result(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def tool_error(message: str, **extra: Any) -> str:
    payload = {"error": message}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _wiki_root() -> Path:
    return Path(os.environ.get("HERMES_LLM_WIKI_ROOT", DEFAULT_WIKI_ROOT)).expanduser()


def _python_bin() -> str:
    return os.environ.get("HERMES_LLM_WIKI_PYTHON", DEFAULT_PYTHON)


def _domain_root() -> Path:
    return Path(os.environ.get("HERMES_LLM_WIKI_DOMAIN_ROOT", DEFAULT_DOMAIN_ROOT)).expanduser()


def _runtime_available() -> bool:
    root = _wiki_root()
    if not (
        root.is_dir()
        and (root / "wiki.scope.json").is_file()
        and (root / "Wiki" / "_data" / "modules").is_dir()
    ):
        return False
    try:
        completed = subprocess.run(
            [_python_bin(), "-m", "llm_wiki_forge", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
    except Exception:
        return False
    return completed.returncode == 0


def _parse_json_stdout(stdout: str) -> dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        raise ValueError("runtime returned empty stdout")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("runtime JSON root is not an object")
    return data


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _norm_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _repo_roots() -> dict[str, Path]:
    root = _wiki_root()
    inventory = _load_json_file(root / "Wiki" / "_data" / "scope.inventory.json")
    roots: dict[str, Path] = {}
    domain = _domain_root()
    for item in inventory.get("repoRoots") or []:
        if not isinstance(item, dict) or item.get("Included") is False:
            continue
        logical = item.get("LogicalRepo")
        actual = str(item.get("ActualRoot") or "").replace("${domainRoot}", str(domain))
        if logical and actual:
            roots[_norm_key(logical)] = Path(actual)
    defaults = {
        "tgdstaxiplus": domain / "RD.TGDS" / "DEV" / "TGDS-TaxiPlus",
        "tgds": domain / "RD.TGDS" / "DEV" / "TGDS",
        "dispatchrule": domain / "DispatchRule",
        "tgdsdispatchwebapi": domain / "TGDS-Dispatch-WebAPI",
        "giscorewebapi": domain / "GIS-Core-WebAPI",
        "multitaxiasr": domain / "MultitaxiASR",
    }
    for key, path in defaults.items():
        roots.setdefault(key, path)
    return roots


def _resolve_repo_root(repo_id: Any, file_path: Any) -> Path | None:
    roots = _repo_roots()
    repo_key = _norm_key(repo_id)
    if repo_key:
        for key, path in roots.items():
            if repo_key == key or repo_key.startswith(key) or key.startswith(repo_key):
                return path

    resolved = _resolve_source_path(file_path, repo_id=repo_id, roots=roots)
    if resolved is not None:
        git_root = _git_toplevel(resolved.parent if resolved.suffix else resolved)
        if git_root is not None:
            return git_root
    return None


def _resolve_source_path(file_path: Any, *, repo_id: Any = None, roots: dict[str, Path] | None = None) -> Path | None:
    raw = str(file_path or "").replace("\\", "/").strip()
    if not raw:
        return None
    domain = _domain_root()
    if raw.startswith("${domainRoot}"):
        return Path(raw.replace("${domainRoot}", str(domain), 1))
    path = Path(raw)
    if path.is_absolute():
        return path

    roots = roots or _repo_roots()
    repo_key = _norm_key(repo_id)
    candidates: list[Path] = []
    if repo_key:
        for key, root_path in roots.items():
            if repo_key == key or repo_key.startswith(key) or key.startswith(repo_key):
                candidates.append(root_path / raw)
    candidates.extend(root_path / raw for root_path in roots.values())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def _git_toplevel(path: Path) -> Path | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    text = completed.stdout.strip()
    return Path(text) if text else None


def _git_info(path: Path) -> dict[str, Any]:
    top = _git_toplevel(path)
    if top is None:
        return {"root": str(path), "available": False}
    info: dict[str, Any] = {"root": str(top), "available": True}
    for key, args in {
        "head": ["rev-parse", "HEAD"],
        "branch": ["rev-parse", "--abbrev-ref", "HEAD"],
    }.items():
        try:
            completed = subprocess.run(
                ["git", "-C", str(top), *args],
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
            )
            info[key] = completed.stdout.strip() if completed.returncode == 0 else None
        except Exception:
            info[key] = None
    return info


def _git_changed_files(repo_root: Path, old_head: str, new_head: str) -> set[str] | None:
    if not old_head or not new_head or old_head == new_head:
        return set()
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--name-only", old_head, new_head],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return {line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()}


def _relative_to(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return None


def _read_line_window(path: Path, start_line: Any, end_line: Any) -> str | None:
    try:
        start = int(start_line or 0)
        end = int(end_line or start or 0)
    except (TypeError, ValueError):
        return None
    if start <= 0 or end < start or not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None
    return "\n".join(lines[start - 1 : end])


def _evidence_code_hash(item: dict[str, Any]) -> str | None:
    value = item.get("code_sha256") or item.get("snippet_sha256")
    if value:
        return str(value)
    code = item.get("code")
    if isinstance(code, str) and code:
        return _sha256_text(code)
    return None


def _evidence_line_hash_matches(item: dict[str, Any]) -> bool | None:
    path = _resolve_source_path(item.get("file_path") or item.get("path"), repo_id=item.get("repo_id") or item.get("module_id"))
    if path is None:
        return None
    stored_hash = _evidence_code_hash(item)
    current_text = _read_line_window(path, item.get("start_line") or item.get("line"), item.get("end_line") or item.get("start_line") or item.get("line"))
    if current_text is None or stored_hash is None:
        return None
    if _sha256_text(current_text) == stored_hash:
        return True
    code = item.get("code")
    if isinstance(code, str) and code.strip():
        return code.strip() in current_text.strip() or current_text.strip() in code.strip()
    return False


def _clip_text(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"... [truncated {len(text) - limit} chars]"


def _clean_detail(value: Any) -> str:
    detail = str(value or DEFAULT_DETAIL).strip().lower()
    return detail if detail in {"compact", "full"} else DEFAULT_DETAIL


def _compact_direct_evidence(items: Any, *, limit: int = COMPACT_DIRECT_EVIDENCE_LIMIT) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        snippet = item.get("snippet") or item.get("code") or item.get("content") or item.get("text") or ""
        row = {
            "repo_id": item.get("repo_id"),
            "module_id": item.get("module_id"),
            "file_path": item.get("file_path") or item.get("path"),
            "symbol": item.get("symbol"),
            "kind": item.get("kind"),
            "start_line": item.get("start_line") or item.get("line"),
            "end_line": item.get("end_line"),
            "confidence": item.get("confidence"),
        }
        if snippet:
            row["snippet"] = _clip_text(snippet, COMPACT_SNIPPET_CHARS)
        compact.append({k: v for k, v in row.items() if v is not None})
    return compact


def _compact_matches(items: Any, *, limit: int = COMPACT_SOURCE_MATCH_LIMIT) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or item.get("snippet") or item.get("line_text") or item.get("text") or ""
        row = {
            "path": item.get("path") or item.get("file_path"),
            "line": item.get("line") or item.get("line_number") or item.get("start_line"),
            "root": item.get("root") or item.get("repo_id") or item.get("module_id"),
        }
        if content:
            row["content"] = _clip_text(content, COMPACT_MATCH_CHARS)
        compact.append({k: v for k, v in row.items() if v is not None})
    return compact


def _compact_candidate_sources(candidate_sources: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    direct = candidate_sources.get("direct_evidence") or []
    compact["direct_evidence"] = _compact_direct_evidence(direct)
    compact["direct_evidence_count"] = len(direct) if isinstance(direct, list) else 0

    for key in ("selected_modules", "modules", "candidate_modules"):
        modules = candidate_sources.get(key)
        if isinstance(modules, list):
            compact[key] = [
                {
                    "module_id": m.get("module_id") or m.get("id"),
                    "name": m.get("name"),
                    "solution_group": m.get("solution_group"),
                    "score": m.get("score"),
                    "reason": _clip_text("; ".join(m.get("reasons") or []) if isinstance(m.get("reasons"), list) else m.get("reason"), 240),
                }
                for m in modules[:5]
                if isinstance(m, dict)
            ]
            compact[f"{key}_count"] = len(modules)

    for key in ("missing", "weaknesses", "open_questions"):
        if key in candidate_sources:
            compact[key] = candidate_sources.get(key)
    return compact


def _selected_modules_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
    selected = routing.get("selected_modules")
    if not isinstance(selected, list):
        candidate_sources = payload.get("candidate_sources") if isinstance(payload.get("candidate_sources"), dict) else {}
        selected = (
            candidate_sources.get("selected_modules")
            or candidate_sources.get("modules")
            or candidate_sources.get("candidate_modules")
            or []
        )
    return [m for m in selected if isinstance(m, dict)]


def _compact_selected_modules(payload: dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
    modules = _selected_modules_from_payload(payload)
    return [
        {
            "module_id": m.get("module_id") or m.get("id"),
            "name": m.get("name"),
            "solution_group": m.get("solution_group"),
            "score": m.get("score"),
            "source_path_count": len(m.get("source_paths") or []) if isinstance(m.get("source_paths"), list) else None,
        }
        for m in modules[:limit]
    ]


def _direct_evidence_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidate_sources = payload.get("candidate_sources") if isinstance(payload.get("candidate_sources"), dict) else {}
    direct = candidate_sources.get("direct_evidence") or payload.get("direct_evidence")
    if not direct:
        synthesis = payload.get("synthesis_inputs") if isinstance(payload.get("synthesis_inputs"), dict) else {}
        direct = synthesis.get("direct_evidence")
    return direct if isinstance(direct, list) else []


def _module_key_from_evidence(item: dict[str, Any]) -> str:
    return str(
        item.get("module_id")
        or item.get("repo_id")
        or item.get("root")
        or "unknown"
    )


def _build_shard_summary(payload: dict[str, Any], direct_evidence: list[dict[str, Any]], *, max_shards: int = 3) -> dict[str, Any]:
    modules = _compact_selected_modules(payload, limit=max_shards)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in direct_evidence:
        if isinstance(item, dict):
            grouped.setdefault(_module_key_from_evidence(item), []).append(item)

    shards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for module in modules:
        key = str(module.get("module_id") or module.get("name") or module.get("solution_group") or "unknown")
        evidence = grouped.get(key) or grouped.get(str(module.get("name"))) or grouped.get(str(module.get("solution_group"))) or []
        shards.append(
            {
                "module_id": module.get("module_id"),
                "name": module.get("name"),
                "solution_group": module.get("solution_group"),
                "evidence_count": len(evidence),
                "evidence_refs": [
                    {
                        "file_path": e.get("file_path") or e.get("path"),
                        "symbol": e.get("symbol"),
                        "start_line": e.get("start_line") or e.get("line"),
                    }
                    for e in evidence[:3]
                    if isinstance(e, dict)
                ],
            }
        )
        seen.add(key)

    for key, evidence in grouped.items():
        if len(shards) >= max_shards:
            break
        if key in seen:
            continue
        shards.append(
            {
                "module_id": key,
                "name": key,
                "solution_group": key,
                "evidence_count": len(evidence),
                "evidence_refs": [
                    {
                        "file_path": e.get("file_path") or e.get("path"),
                        "symbol": e.get("symbol"),
                        "start_line": e.get("start_line") or e.get("line"),
                    }
                    for e in evidence[:3]
                    if isinstance(e, dict)
                ],
            }
        )

    shape = "multi_module" if len(shards) > 1 else "single_module"
    return {
        "query_shape": shape,
        "max_shards": max_shards,
        "shards": shards,
        "shard_count": len(shards),
    }


def _query_terms(question: str) -> set[str]:
    terms: set[str] = set()
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|\d{2,}", question):
        terms.add(token.lower())
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", question):
        terms.add(chunk)
        for size in (2, 3):
            if len(chunk) >= size:
                terms.update(chunk[i : i + size] for i in range(0, len(chunk) - size + 1))
    return terms


def _freshness_sensitive_question(question: str) -> bool:
    lowered = question.lower()
    return any(keyword.lower() in lowered for keyword in FRESHNESS_KEYWORDS)


def _question_similarity(current_question: str, cached_question: str) -> dict[str, Any]:
    current_terms = _query_terms(current_question)
    cached_terms = _query_terms(cached_question)
    if not current_terms or not cached_terms:
        return {"status": "related_only", "score": 0.0, "overlap": []}
    overlap = current_terms & cached_terms
    current_coverage = len(overlap) / max(1, len(current_terms))
    cached_coverage = len(overlap) / max(1, len(cached_terms))
    score = round((current_coverage * 0.65) + (cached_coverage * 0.35), 4)
    current_lower = current_question.lower().strip()
    cached_lower = cached_question.lower().strip()
    if current_lower and cached_lower and (current_lower in cached_lower or cached_lower in current_lower):
        score = max(score, 0.9)
    if current_coverage >= 0.72 and cached_coverage >= 0.5:
        status = "high"
    elif current_coverage >= 0.42 or len(overlap) >= 3:
        status = "partial"
    else:
        status = "related_only"
    return {
        "status": status,
        "score": score,
        "overlap": sorted(overlap, key=lambda x: (-len(x), x))[:12],
        "current_term_count": len(current_terms),
        "cached_term_count": len(cached_terms),
        "current_coverage": round(current_coverage, 4),
        "cached_coverage": round(cached_coverage, 4),
    }


def _looks_exact_identifier(question: str) -> bool:
    return bool(re.search(r"\b[A-Za-z_][A-Za-z0-9_]*[A-Z][A-Za-z0-9_]*\b", question))


def _recent_query_runs(root: Path, *, days: int = DEFAULT_REUSE_DAYS) -> list[Path]:
    runs_dir = root / "Wiki" / "_data" / "query_runs"
    if not runs_dir.is_dir():
        return []
    cutoff = time.time() - max(1, days) * 86400
    files = [p for p in runs_dir.glob("*.json") if p.is_file() and p.stat().st_mtime >= cutoff]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:RECENT_QUERY_RUN_LIMIT]


def _score_query_run(path: Path, question: str, terms: set[str]) -> tuple[int, dict[str, Any] | None, dict[str, Any]]:
    haystack = path.stem.lower()
    payload: dict[str, Any] | None = None
    similarity = {"status": "related_only", "score": 0.0, "overlap": []}
    try:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        if isinstance(payload, dict):
            cached_question = str(payload.get("question") or "")
            haystack += " " + cached_question.lower()
            similarity = _question_similarity(question, cached_question)
    except Exception:
        payload = None
    score = 0
    for term in terms:
        if term.lower() in haystack:
            score += 2 if len(term) >= 3 else 1
    if question and question.lower() in haystack:
        score += 8
    score += int(float(similarity.get("score") or 0) * 10)
    return score, payload, similarity


def _find_reusable_query_run(question: str, *, days: int = DEFAULT_REUSE_DAYS) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
    if _looks_exact_identifier(question):
        return None
    if _freshness_sensitive_question(question):
        return None
    root = _wiki_root()
    terms = _query_terms(question)
    if not terms:
        return None

    best: tuple[int, Path, dict[str, Any], dict[str, Any]] | None = None
    for path in _recent_query_runs(root, days=days):
        score, payload, similarity = _score_query_run(path, question, terms)
        if payload is None or score < 6:
            continue
        if similarity.get("status") == "related_only":
            continue
        if best is None or score > best[0]:
            best = (score, path, payload, similarity)
    if best is None:
        return None
    return best[1], best[2], best[3]


def _source_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = payload.get("source_snapshot")
    if isinstance(snapshot, dict):
        return snapshot
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("source_snapshot"), dict):
        return metadata["source_snapshot"]
    return {}


def _snapshot_repos(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    repos = snapshot.get("repos")
    if isinstance(repos, dict):
        return {str(k): v for k, v in repos.items() if isinstance(v, dict)}
    if isinstance(repos, list):
        result: dict[str, dict[str, Any]] = {}
        for item in repos:
            if isinstance(item, dict):
                key = str(item.get("logical_repo") or item.get("name") or item.get("root") or "")
                if key:
                    result[key] = item
        return result
    return {}


def _evidence_repo_keys(direct_evidence: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for item in direct_evidence:
        if not isinstance(item, dict):
            continue
        repo_id = item.get("repo_id") or item.get("module_id")
        if repo_id:
            keys.add(_norm_key(repo_id))
    return keys


def _current_repo_heads_for_evidence(direct_evidence: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in direct_evidence:
        if not isinstance(item, dict):
            continue
        repo_id = item.get("repo_id") or item.get("module_id") or "unknown"
        repo_root = _resolve_repo_root(repo_id, item.get("file_path") or item.get("path"))
        if repo_root is None:
            continue
        info = _git_info(repo_root)
        result[_norm_key(repo_id)] = {
            "repo_id": repo_id,
            "root": info.get("root") or str(repo_root),
            "head": info.get("head"),
            "branch": info.get("branch"),
            "available": bool(info.get("available")),
        }
    return result


def _stored_repo_for_key(stored_repos: dict[str, dict[str, Any]], key: str) -> dict[str, Any] | None:
    norm = _norm_key(key)
    for stored_key, info in stored_repos.items():
        stored_norm = _norm_key(stored_key)
        if norm == stored_norm or norm.startswith(stored_norm) or stored_norm.startswith(norm):
            return info
        logical_norm = _norm_key(info.get("logical_repo") or info.get("repo_id") or info.get("name"))
        if logical_norm and (norm == logical_norm or norm.startswith(logical_norm) or logical_norm.startswith(norm)):
            return info
    return None


def _evidence_paths_touched_by_diff(
    direct_evidence: list[dict[str, Any]],
    current_repos: dict[str, dict[str, Any]],
    stored_repos: dict[str, dict[str, Any]],
) -> bool | None:
    any_checked = False
    for item in direct_evidence:
        if not isinstance(item, dict):
            continue
        repo_key = _norm_key(item.get("repo_id") or item.get("module_id"))
        current = current_repos.get(repo_key)
        stored = _stored_repo_for_key(stored_repos, repo_key)
        if not current or not stored:
            continue
        old_head = str(stored.get("head") or "")
        new_head = str(current.get("head") or "")
        if not old_head or not new_head or old_head == new_head:
            continue
        repo_root = Path(str(current.get("root") or ""))
        changed = _git_changed_files(repo_root, old_head, new_head)
        if changed is None:
            return None
        path = _resolve_source_path(item.get("file_path") or item.get("path"), repo_id=item.get("repo_id") or item.get("module_id"))
        rel = _relative_to(path, repo_root) if path else None
        any_checked = True
        if rel and rel in changed:
            return True
    return False if any_checked else None


def _snippet_validation(direct_evidence: list[dict[str, Any]]) -> tuple[str, list[str]]:
    actions: list[str] = []
    checked = 0
    mismatched = 0
    unknown = 0
    for item in direct_evidence[:8]:
        if not isinstance(item, dict):
            continue
        match = _evidence_line_hash_matches(item)
        if match is True:
            checked += 1
        elif match is False:
            checked += 1
            mismatched += 1
        else:
            unknown += 1
    actions.append(f"snippet_hash_checked={checked}")
    if unknown:
        actions.append(f"snippet_hash_unknown={unknown}")
    if mismatched:
        actions.append(f"snippet_hash_mismatch={mismatched}")
        return "mismatch", actions
    if checked:
        return "match", actions
    return "unknown", actions


def _validation_index_path() -> Path:
    return _wiki_root() / VALIDATION_INDEX


def _validation_key(pack_path: Path, current_repos: dict[str, dict[str, Any]]) -> str:
    heads = "|".join(
        f"{key}:{info.get('head') or ''}"
        for key, info in sorted(current_repos.items())
    )
    return _sha256_text(f"{pack_path.resolve()}|{heads}")


def _load_validation_index() -> dict[str, Any]:
    return _load_json_file(_validation_index_path())


def _record_validation(pack_path: Path, current_repos: dict[str, dict[str, Any]], validation: dict[str, Any]) -> None:
    path = _validation_index_path()
    index = _load_validation_index()
    records = index.get("records")
    if not isinstance(records, dict):
        records = {}
    key = _validation_key(pack_path, current_repos)
    records[key] = {
        "pack_path": str(pack_path),
        "validated_at": validation.get("validation_checked_at"),
        "reuse_decision": validation.get("reuse_decision"),
        "freshness_status": validation.get("freshness_status"),
        "similarity_status": validation.get("similarity_status"),
        "repo_heads": {
            repo_key: info.get("head")
            for repo_key, info in current_repos.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"version": 1, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _validate_reuse_candidate(
    pack_path: Path,
    payload: dict[str, Any],
    similarity: dict[str, Any],
) -> dict[str, Any]:
    direct_evidence = _direct_evidence_from_payload(payload)
    validation = {
        "reuse_decision": "bypass",
        "freshness_status": "legacy_unknown",
        "similarity_status": similarity.get("status") or "related_only",
        "similarity_score": similarity.get("score", 0.0),
        "validation_checked_at": _now_iso(),
        "validation_actions": [f"similarity={similarity.get('status')}"],
    }
    if similarity.get("status") == "partial":
        validation["reuse_decision"] = "hint_only"
        validation["freshness_status"] = "legacy_unknown"
        validation["validation_actions"].append("partial_similarity_requires_narrow_check")
        return validation
    if similarity.get("status") != "high":
        validation["validation_actions"].append("related_only_skipped")
        return validation

    snapshot = _source_snapshot(payload)
    stored_repos = _snapshot_repos(snapshot)
    current_repos = _current_repo_heads_for_evidence(direct_evidence)
    if not stored_repos:
        snippet_status, actions = _snippet_validation(direct_evidence)
        validation["validation_actions"].extend(["legacy_pack_no_source_snapshot", *actions])
        if snippet_status == "match":
            validation["reuse_decision"] = "validated_reuse"
            validation["freshness_status"] = "legacy_unknown"
            try:
                _record_validation(pack_path, current_repos, validation)
            except Exception as exc:
                validation["validation_actions"].append(f"validation_index_write_failed={type(exc).__name__}")
        elif snippet_status == "mismatch":
            validation["reuse_decision"] = "bypass"
            validation["freshness_status"] = "stale_logic_changed"
        else:
            validation["reuse_decision"] = "hint_only"
            validation["freshness_status"] = "legacy_unknown"
        return validation

    changed_heads = []
    unavailable = []
    for repo_key in _evidence_repo_keys(direct_evidence):
        stored = _stored_repo_for_key(stored_repos, repo_key)
        current = current_repos.get(repo_key)
        if not stored or not current or not current.get("available"):
            unavailable.append(repo_key)
            continue
        if stored.get("head") != current.get("head"):
            changed_heads.append(repo_key)

    if unavailable:
        validation["validation_actions"].append(f"repo_status_unavailable={','.join(sorted(unavailable))}")
    if not changed_heads and not unavailable:
        validation["reuse_decision"] = "direct_reuse"
        validation["freshness_status"] = "fresh"
        validation["validation_actions"].append("repo_heads_match")
        return validation

    touched = _evidence_paths_touched_by_diff(direct_evidence, current_repos, stored_repos)
    validation["validation_actions"].append(f"changed_repo_heads={','.join(sorted(changed_heads)) or 'none'}")
    if touched is False:
        validation["reuse_decision"] = "validated_reuse"
        validation["freshness_status"] = "version_changed_checked_ok"
        validation["validation_actions"].append("changed_files_do_not_touch_evidence")
        try:
            _record_validation(pack_path, current_repos, validation)
        except Exception as exc:
            validation["validation_actions"].append(f"validation_index_write_failed={type(exc).__name__}")
        return validation

    snippet_status, actions = _snippet_validation(direct_evidence)
    validation["validation_actions"].extend(actions)
    if snippet_status == "match":
        validation["reuse_decision"] = "validated_reuse"
        validation["freshness_status"] = "version_changed_checked_ok"
        try:
            _record_validation(pack_path, current_repos, validation)
        except Exception as exc:
            validation["validation_actions"].append(f"validation_index_write_failed={type(exc).__name__}")
    elif snippet_status == "mismatch":
        validation["reuse_decision"] = "bypass"
        validation["freshness_status"] = "stale_logic_changed"
    else:
        validation["reuse_decision"] = "hint_only"
        validation["freshness_status"] = "version_changed_needs_check"
    return validation


def _run_runtime(command_name: str, args: list[str], *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    root = _wiki_root()
    if not root.is_dir():
        raise FileNotFoundError(f"LLM Wiki root not found: {root}")

    module = RUNTIME_MODULES.get(command_name)
    if not module:
        raise ValueError(f"unsupported LLM Wiki runtime command: {command_name}")
    completed = run_packaged_module(
        Path(_python_bin()),
        module,
        ["--wiki-root", str(root), *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or f"exit code {completed.returncode}"
        raise RuntimeError(detail[-2000:])
    return _parse_json_stdout(completed.stdout)


def _source_search_summary(source_search: dict[str, Any]) -> tuple[list[str], list[str]]:
    if not isinstance(source_search, dict):
        return [], []

    roots = source_search.get("searched_roots") or source_search.get("roots") or []
    patterns = source_search.get("searched_patterns") or source_search.get("patterns") or []

    if not patterns and source_search.get("pattern"):
        patterns = [source_search["pattern"]]
    if not roots and source_search.get("root"):
        roots = [source_search["root"]]

    return list(roots or []), list(patterns or [])


def _next_action(decision: str) -> str:
    return {
        "answer_from_graph": "answer",
        "answer_from_verified_search": "answer",
        "needs_semantic_expansion": "run_source_search",
        "needs_user_clarification": "ask_clarification",
        "not_found_after_verified_search": "no_direct_evidence",
    }.get(decision or "", "inspect_result")


def _normalize_query_result(
    payload: dict[str, Any],
    *,
    detail: str = DEFAULT_DETAIL,
    reused_evidence_pack: bool = False,
    evidence_pack_path: str | None = None,
    max_shards: int = 3,
    reuse_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detail = _clean_detail(detail)
    graph_runtime = payload.get("graph_runtime") if isinstance(payload.get("graph_runtime"), dict) else {}
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    candidate_sources = (
        payload.get("candidate_sources") if isinstance(payload.get("candidate_sources"), dict) else {}
    )
    source_search = payload.get("source_search") if isinstance(payload.get("source_search"), dict) else {}
    searched_roots, searched_patterns = _source_search_summary(source_search)
    direct_evidence = _direct_evidence_from_payload(payload)
    decision = str(payload.get("decision") or "")
    if not decision and direct_evidence:
        decision = "answer_from_graph"
    reuse_validation = reuse_validation or {}
    if reuse_validation.get("reuse_decision") == "hint_only":
        decision = "needs_semantic_expansion"
    evidence_pack = graph_runtime.get("evidence_pack") or payload.get("evidence_pack") or evidence_pack_path
    if detail == "compact":
        candidate_sources_out = _compact_candidate_sources(candidate_sources)
        if not candidate_sources_out.get("direct_evidence") and direct_evidence:
            candidate_sources_out["direct_evidence"] = _compact_direct_evidence(direct_evidence)
            candidate_sources_out["direct_evidence_count"] = len(direct_evidence)
        source_search_out = {
            "total_count": source_search.get("total_count", 0),
            "truncated": bool(source_search.get("truncated")),
            "matches": _compact_matches(source_search.get("matches") or []),
            "omitted_count": max(
                0,
                len(source_search.get("matches") or []) - COMPACT_SOURCE_MATCH_LIMIT,
            ),
            "read_verify": source_search.get("read_verify"),
            "limit_policy": source_search.get("limit_policy"),
        }
        direct_evidence_out = _compact_direct_evidence(direct_evidence)
    else:
        candidate_sources_out = candidate_sources
        source_search_out = source_search
        direct_evidence_out = direct_evidence

    routing_summary = {
        "selected_modules": _compact_selected_modules(payload),
        "selected_module_count": len(_selected_modules_from_payload(payload)),
        "exact_identifier_gate": _looks_exact_identifier(str(payload.get("question") or "")),
    }
    shard_summary = _build_shard_summary(payload, direct_evidence, max_shards=max_shards)

    return {
        "decision": decision,
        "why": reuse_validation.get("why") or payload.get("why") or "",
        "next_action": _next_action(decision),
        "detail": detail,
        "reused_evidence_pack": reused_evidence_pack,
        "reuse_decision": reuse_validation.get("reuse_decision") or ("direct_reuse" if reused_evidence_pack else "bypass"),
        "freshness_status": reuse_validation.get("freshness_status") or ("fresh" if reused_evidence_pack else None),
        "similarity_status": reuse_validation.get("similarity_status"),
        "similarity_score": reuse_validation.get("similarity_score"),
        "validation_checked_at": reuse_validation.get("validation_checked_at"),
        "validation_actions": reuse_validation.get("validation_actions") or [],
        "telemetry": {
            "detail": detail,
            "reused_evidence_pack": reused_evidence_pack,
            "reuse_decision": reuse_validation.get("reuse_decision") or ("direct_reuse" if reused_evidence_pack else "bypass"),
            "freshness_status": reuse_validation.get("freshness_status"),
            "similarity_status": reuse_validation.get("similarity_status"),
            "direct_evidence_count": len(direct_evidence),
            "selected_module_count": routing_summary["selected_module_count"],
            "shard_count": shard_summary["shard_count"],
            "compact_direct_evidence_limit": COMPACT_DIRECT_EVIDENCE_LIMIT if detail == "compact" else None,
            "compact_source_match_limit": COMPACT_SOURCE_MATCH_LIMIT if detail == "compact" else None,
        },
        "coverage": coverage,
        "routing": routing_summary,
        "shards": shard_summary,
        "candidate_sources": candidate_sources_out,
        "direct_evidence": direct_evidence_out,
        "direct_evidence_count": len(direct_evidence),
        "searched_roots": searched_roots,
        "searched_patterns": searched_patterns,
        "evidence_pack": evidence_pack,
        "graph_status": graph_runtime.get("status"),
        "source_search": source_search_out,
        "answer_gate": payload.get("answer_gate"),
        "ambiguity_gate": payload.get("ambiguity_gate"),
    }


def llm_wiki_query_tool(args: dict[str, Any], **_kwargs) -> str:
    question = str(args.get("question") or "").strip()
    if not question:
        return tool_error("question is required")

    try:
        top = max(1, min(int(args.get("top", 5)), 20))
        extract_limit = max(0, min(int(args.get("extract_limit", 4)), 20))
        max_shards = max(1, min(int(args.get("max_shards", 3)), 3))
        reuse_days = max(1, min(int(args.get("reuse_days", DEFAULT_REUSE_DAYS)), 30))
    except (TypeError, ValueError):
        return tool_error("top, extract_limit, max_shards, and reuse_days must be integers")

    detail = _clean_detail(args.get("detail"))
    reuse_recent = args.get("reuse_recent", True)
    reuse_recent = False if isinstance(reuse_recent, str) and reuse_recent.lower() in {"false", "0", "no"} else bool(reuse_recent)

    try:
        bypass_validation: dict[str, Any] | None = None
        if reuse_recent:
            reusable = _find_reusable_query_run(question, days=reuse_days)
            if reusable is not None:
                evidence_path, cached_payload, similarity = reusable
                cached_payload = {**cached_payload, "question": cached_payload.get("question") or question}
                reuse_validation = _validate_reuse_candidate(evidence_path, cached_payload, similarity)
                reuse_decision = reuse_validation.get("reuse_decision")
                if reuse_decision in {"direct_reuse", "validated_reuse", "hint_only"}:
                    return tool_result(
                        _normalize_query_result(
                            cached_payload,
                            detail=detail,
                            reused_evidence_pack=True,
                            evidence_pack_path=str(evidence_path),
                            max_shards=max_shards,
                            reuse_validation=reuse_validation,
                        )
                    )
                bypass_validation = reuse_validation

        payload = _run_runtime(
            "query",
            [
                "--question",
                question,
                "--top",
                str(top),
                "--extract-limit",
                str(extract_limit),
                "--json",
            ],
        )
        payload = {**payload, "question": payload.get("question") or question}
        return tool_result(
            _normalize_query_result(
                payload,
                detail=detail,
                max_shards=max_shards,
                reuse_validation=bypass_validation,
            )
        )
    except subprocess.TimeoutExpired:
        return tool_error("LLM Wiki query timed out", next_action="retry_or_narrow_question")
    except Exception as exc:
        return tool_error(str(exc), next_action="cannot_verify_direct_evidence")


def llm_wiki_source_search_tool(args: dict[str, Any], **_kwargs) -> str:
    pattern = str(args.get("pattern") or "").strip()
    if not pattern:
        return tool_error("pattern is required")
    if "|" in pattern:
        return tool_error("pattern must be a single fixed string; do not use pipe-combined patterns")

    root = str(args.get("root") or "").strip()
    detail = _clean_detail(args.get("detail"))
    try:
        max_limit = 80 if detail == "full" else 20
        limit = max(1, min(int(args.get("limit", 20)), max_limit))
    except (TypeError, ValueError):
        return tool_error("limit must be an integer")

    runtime_args = ["--pattern", pattern, "--limit", str(limit), "--json"]
    if root:
        runtime_args.extend(["--root", root])

    try:
        payload = _run_runtime("source-search", runtime_args)
        searched_roots, searched_patterns = _source_search_summary(payload)
        raw_matches = payload.get("matches") or []
        matches = raw_matches if detail == "full" else _compact_matches(raw_matches)
        return tool_result(
            {
                "next_action": "read_or_answer" if payload.get("total_count") else "no_direct_evidence",
                "detail": detail,
                "telemetry": {
                    "detail": detail,
                    "requested_limit": args.get("limit", 20),
                    "effective_limit": limit,
                    "match_count_returned": len(matches) if isinstance(matches, list) else 0,
                    "raw_match_count": len(raw_matches) if isinstance(raw_matches, list) else 0,
                },
                "searched_roots": searched_roots or ([root] if root else []),
                "searched_patterns": searched_patterns or [pattern],
                "limit": limit,
                "total_count": payload.get("total_count", 0),
                "truncated": bool(payload.get("truncated")),
                "matches": matches,
                "omitted_count": max(0, len(raw_matches) - len(matches)) if isinstance(raw_matches, list) else 0,
                "read_verify": payload.get("read_verify"),
                "limit_policy": payload.get("limit_policy"),
            }
        )
    except subprocess.TimeoutExpired:
        return tool_error("LLM Wiki source search timed out", next_action="narrow_pattern_or_root")
    except Exception as exc:
        return tool_error(str(exc), next_action="cannot_verify_direct_evidence")


LLM_WIKI_QUERY_SCHEMA = {
    "name": "llm_wiki_query",
    "description": (
        "Query the local LLM Wiki through the canonical query_orchestrator. "
        "Use this first for TGDS, TaxiPlus, dispatch, fare, payment, API, scheduler, "
        "or code behavior questions. Read-only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The user's code or business-logic question.",
            },
            "top": {
                "type": "integer",
                "description": "Maximum graph module candidates. Defaults to 5.",
                "default": 5,
            },
            "extract_limit": {
                "type": "integer",
                "description": "Maximum source files for graph extraction. Defaults to 4.",
                "default": 4,
            },
            "detail": {
                "type": "string",
                "enum": ["compact", "full"],
                "description": "Payload detail level. Slack should use compact; full is for CLI/debug.",
                "default": "compact",
            },
            "reuse_recent": {
                "type": "boolean",
                "description": "Reuse a recent matching evidence pack before running a fresh broad query.",
                "default": True,
            },
            "reuse_days": {
                "type": "integer",
                "description": "How many recent days of query_runs may be reused. Defaults to 7, max 30.",
                "default": 7,
            },
            "max_shards": {
                "type": "integer",
                "description": "Maximum deterministic module shards to summarize for broad queries. Defaults to 3.",
                "default": 3,
            },
        },
        "required": ["question"],
    },
}


LLM_WIKI_SOURCE_SEARCH_SCHEMA = {
    "name": "llm_wiki_source_search",
    "description": (
        "Run deterministic fixed-string source_search through the local LLM Wiki runtime. "
        "Use only after llm_wiki_query asks for semantic expansion or exact identifier verification. "
        "Read-only; no regex pipes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "One fixed string to search for. Do not combine alternatives with pipes.",
            },
            "root": {
                "type": "string",
                "description": "Optional source root hint under the configured DispatchRawdata roots.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum matches. Defaults to 20; compact mode caps at 20, full mode caps at 80.",
                "default": 20,
            },
            "detail": {
                "type": "string",
                "enum": ["compact", "full"],
                "description": "Payload detail level. Compact returns capped snippets; full returns raw matches.",
                "default": "compact",
            },
        },
        "required": ["pattern"],
    },
}
