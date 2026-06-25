from __future__ import annotations

import argparse
import json
import re
import selectors
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


DISPATCH_ROOT = Path("/home/tedhsu/codebases/dispatch")
DEFAULT_WIKI_REGISTRY = Path("/home/tedhsu/llm-wiki/registry.json")
GREP_BIN = Path("/usr/bin/grep")
DEFAULT_SEARCH_LIMIT = 20
EXPANDED_SEARCH_LIMIT = 80
CORE_INCLUDE_GLOBS = [
    "*.json",
    "*.config",
    "*.xml",
    "*.yaml",
    "*.yml",
    "*.toml",
    "*.ini",
    "*.properties",
    "*.props",
    "*.targets",
    "*.md",
    "*.txt",
    "Dockerfile",
    "Makefile",
]
LANGUAGE_INCLUDE_GLOBS = {
    "dotnet": [
        "*.cs",
        "*.cshtml",
        "*.asax",
        "*.ashx",
        "*.aspx",
        "*.ascx",
        "*.vb",
        "*.fs",
        "*.csproj",
        "*.vbproj",
        "*.fsproj",
        "*.sln",
        "*.resx",
        "*.js",
        "*.jsx",
        "*.ts",
        "*.tsx",
        "*.html",
        "*.htm",
        "*.css",
        "*.scss",
        "*.less",
    ],
    "android": ["*.kt", "*.kts", "*.java", "*.gradle", "*.xml", "*.properties"],
    "kotlin": ["*.kt", "*.kts", "*.java", "*.gradle", "*.xml", "*.properties"],
    "java": ["*.java", "*.kt", "*.kts", "*.gradle", "*.xml", "*.properties"],
    "javascript": ["*.js", "*.jsx", "*.mjs", "*.cjs", "*.ts", "*.tsx", "*.vue", "*.svelte", "*.html", "*.css", "*.scss", "*.less"],
    "typescript": ["*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs", "*.cjs", "*.vue", "*.svelte", "*.html", "*.css", "*.scss", "*.less"],
    "python": ["*.py", "*.pyw", "*.ipynb"],
    "go": ["*.go", "go.mod", "go.sum"],
    "rust": ["*.rs", "Cargo.toml", "Cargo.lock"],
    "swift": ["*.swift", "*.m", "*.mm", "*.h", "*.plist", "*.pbxproj"],
    "cpp": ["*.c", "*.cc", "*.cpp", "*.cxx", "*.h", "*.hh", "*.hpp", "*.hxx", "*.cmake", "CMakeLists.txt"],
    "php": ["*.php", "*.phtml"],
    "ruby": ["*.rb", "*.rake", "Gemfile"],
    "shell": ["*.sh", "*.bash", "*.zsh", "*.ps1"],
    "terraform": ["*.tf", "*.tfvars", "*.hcl"],
    "proto": ["*.proto"],
}
LANGUAGE_ALIASES = {
    "c#": "dotnet",
    "csharp": "dotnet",
    "cs": "dotnet",
    "net": "dotnet",
    "netframework": "dotnet",
    "aspnet": "dotnet",
    "aspnetcore": "dotnet",
    "vbnet": "dotnet",
    "fsharp": "dotnet",
    "node": "javascript",
    "nodejs": "javascript",
    "js": "javascript",
    "web": "javascript",
    "frontend": "javascript",
    "ts": "typescript",
    "ios": "swift",
    "objectivec": "swift",
    "c++": "cpp",
    "cplusplus": "cpp",
    "c": "cpp",
    "grpc": "proto",
}
EXTENSION_LANGUAGE_HINTS = {
    ".cs": "dotnet",
    ".cshtml": "dotnet",
    ".asax": "dotnet",
    ".ashx": "dotnet",
    ".aspx": "dotnet",
    ".ascx": "dotnet",
    ".csproj": "dotnet",
    ".vbproj": "dotnet",
    ".fsproj": "dotnet",
    ".sln": "dotnet",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".gradle": "android",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".py": "python",
    ".go": "go",
    ".rs": "rust",
    ".swift": "swift",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".php": "php",
    ".rb": "ruby",
    ".sh": "shell",
    ".ps1": "shell",
    ".tf": "terraform",
    ".proto": "proto",
}
FALLBACK_LANGUAGE_HINTS = ["dotnet", "android", "kotlin", "java", "javascript", "typescript", "python", "go", "rust", "swift", "cpp", "php", "ruby", "shell", "terraform", "proto"]
DEFAULT_INCLUDE_GLOBS = [
    "*.cs",
    "*.json",
    "*.config",
    "*.cshtml",
    "*.asax",
    "*.ashx",
    "*.xml",
    "*.kt",
    "*.kts",
    "*.gradle",
]
SQL_INCLUDE_GLOBS = ["*.sql"]
KNOWN_METADATA_SUFFIXES = {
    glob[1:].lower()
    for glob in CORE_INCLUDE_GLOBS + [item for values in LANGUAGE_INCLUDE_GLOBS.values() for item in values]
    if glob.startswith("*.")
}
DEFAULT_EXCLUDE_DIRS = [
    ".git",
    ".vs",
    "bin",
    "build",
    "coverage",
    "obj",
    "node_modules",
    "packages",
    "TestResults",
    "graphify-out",
]
FALLBACK_ROOTS = [
    "/home/tedhsu/codebases/dispatch/RD.TGDS/DEV/TGDS-TaxiPlus/01_Code/TGDS.WebAPI",
    "/home/tedhsu/codebases/dispatch/TGDS-Dispatch-WebAPI",
    "/home/tedhsu/codebases/dispatch/DispatchRule",
    "/home/tedhsu/codebases/dispatch/RD.TGDS/DEV/TGDS/CoreServers",
]
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}")
UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _json_error(message: str, *, query: str = "", patterns: list[str] | None = None) -> dict[str, Any]:
    return {
        "query": query,
        "patterns": patterns or [],
        "roots": [],
        "matches": [],
        "total_count": 0,
        "truncated": False,
        "errors": [message],
        "searched_at": _now_iso(),
    }


def extract_query_patterns(query: str, *, limit: int = 8) -> list[str]:
    """Split text into lexical grep patterns for diagnostics only.

    This helper does not do semantic expansion. Normal Slack/Hermes query
    flows should pass explicit ``--pattern`` values generated by the outer LLM.
    """
    patterns = [match.group(0) for match in TOKEN_RE.finditer(query)]
    return _dedupe(patterns)[:limit]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_language_hint(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.startswith("net") or re.fullmatch(r"v\d+(?:\.\d+)*", text):
        return "dotnet"
    compact = re.sub(r"[^a-z0-9+#]+", "", text)
    if compact.startswith("net") or compact in {"dotnetcore", "dotnetframework"}:
        return "dotnet"
    return LANGUAGE_ALIASES.get(compact) or (compact if compact in LANGUAGE_INCLUDE_GLOBS else None)


def _path_variables(wiki_root: Path) -> dict[str, str]:
    scope = _load_json(wiki_root / "wiki.scope.json")
    variables = scope.get("pathVariables") if isinstance(scope.get("pathVariables"), dict) else {}
    return {str(key): str(value) for key, value in variables.items()}


def _expand_vars(value: str, variables: dict[str, str]) -> str:
    result = value
    for key, replacement in variables.items():
        result = result.replace("${" + key + "}", replacement)
    return result


def _path_glob_from_value(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("\\", "/")
    name = Path(normalized).name
    if name in {"Dockerfile", "Makefile", "Gemfile", "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "CMakeLists.txt"}:
        return name
    suffix = Path(normalized).suffix.lower()
    if not suffix or suffix == ".sql":
        return None
    if suffix not in KNOWN_METADATA_SUFFIXES:
        return None
    if not re.fullmatch(r"\.[a-z0-9][a-z0-9+_-]{0,12}", suffix):
        return None
    return f"*{suffix}"


def _language_hint_from_path(value: Any) -> str | None:
    text = str(value or "").strip().replace("\\", "/")
    suffix = Path(text).suffix.lower()
    if suffix in {".csproj", ".vbproj", ".fsproj", ".sln"}:
        return "dotnet"
    if Path(text).name in {"go.mod", "go.sum"}:
        return "go"
    if Path(text).name in {"Cargo.toml", "Cargo.lock"}:
        return "rust"
    return EXTENSION_LANGUAGE_HINTS.get(suffix)


def _collect_path_globs(value: Any, globs: set[str], languages: set[str]) -> None:
    if isinstance(value, str):
        glob = _path_glob_from_value(value)
        if glob:
            globs.add(glob)
        language = _language_hint_from_path(value)
        if language:
            languages.add(language)
    elif isinstance(value, dict):
        for nested in value.values():
            _collect_path_globs(nested, globs, languages)
    elif isinstance(value, list):
        for nested in value:
            _collect_path_globs(nested, globs, languages)


def _registry_language_profile(wiki_root: Path) -> tuple[set[str], set[str]]:
    languages: set[str] = set()
    globs: set[str] = set()
    data = _load_json(DEFAULT_WIKI_REGISTRY)
    current = str(wiki_root.resolve())
    for item in data.get("roots") or []:
        if not isinstance(item, dict):
            continue
        try:
            item_root = str(Path(str(item.get("wiki_root") or "")).expanduser().resolve())
        except OSError:
            continue
        if item_root != current:
            continue
        for field in ("platforms", "languages"):
            values = item.get(field) if isinstance(item.get(field), list) else []
            for value in values:
                language = _normalize_language_hint(value)
                if language:
                    languages.add(language)
        for repo in item.get("repos") or []:
            _collect_path_globs(repo, globs, languages)
    return languages, globs


def _scope_language_profile(wiki_root: Path) -> tuple[set[str], set[str]]:
    languages: set[str] = set()
    globs: set[str] = set()
    scope = _load_json(wiki_root / "wiki.scope.json")
    variables = _path_variables(wiki_root)
    for repo in scope.get("repos") or []:
        if not isinstance(repo, dict):
            continue
        language = _normalize_language_hint(repo.get("platform"))
        if language:
            languages.add(language)
        for key in ("projectFile",):
            value = repo.get(key)
            if isinstance(value, str):
                _collect_path_globs(_expand_vars(value, variables), globs, languages)
        for target in repo.get("targets") or []:
            if not isinstance(target, dict):
                continue
            language = _normalize_language_hint(target.get("platform") or target.get("type"))
            if language:
                languages.add(language)
            for key in ("projectFile",):
                value = target.get(key)
                if isinstance(value, str):
                    _collect_path_globs(_expand_vars(value, variables), globs, languages)

    inventory = _load_json(wiki_root / "Wiki" / "_data" / "scope.inventory.json")
    for item in inventory.get("items") or []:
        if not isinstance(item, dict):
            continue
        language = _normalize_language_hint(item.get("type"))
        if language:
            languages.add(language)
        for key in ("projectFiles", "solutionFiles", "solutionFilterFiles"):
            _collect_path_globs(item.get(key), globs, languages)
        if int(item.get("csharpFiles") or 0) > 0:
            languages.add("dotnet")
    return languages, globs


def _module_language_profile(wiki_root: Path) -> tuple[set[str], set[str]]:
    languages: set[str] = set()
    globs: set[str] = set()
    modules_dir = wiki_root / "Wiki" / "_data" / "modules"
    for path in modules_dir.glob("*.json"):
        data = _load_json(path)
        if not data:
            continue
        contract = data.get("technical_contract") if isinstance(data.get("technical_contract"), dict) else {}
        for framework in contract.get("runtime_frameworks") or []:
            language = _normalize_language_hint(framework)
            if language:
                languages.add(language)
        for key in (
            "solutions",
            "project_files",
            "entry_points",
            "route_surface",
            "ui_surface",
            "service_registrations",
        ):
            _collect_path_globs(contract.get(key), globs, languages)
    return languages, globs


def _include_profile(wiki_root: Path, *, include_sql: bool) -> dict[str, Any]:
    languages: set[str] = set()
    metadata_globs: set[str] = set()
    for collector in (_registry_language_profile, _scope_language_profile, _module_language_profile):
        found_languages, found_globs = collector(wiki_root)
        languages.update(found_languages)
        metadata_globs.update(found_globs)

    fallback_used = False
    unknown_language_metadata = bool(metadata_globs) and not languages
    if not languages and not metadata_globs:
        fallback_used = True
        languages.update(FALLBACK_LANGUAGE_HINTS)
    elif unknown_language_metadata:
        fallback_used = True
        languages.update(FALLBACK_LANGUAGE_HINTS)

    include_globs = list(CORE_INCLUDE_GLOBS)
    for language in sorted(languages):
        include_globs.extend(LANGUAGE_INCLUDE_GLOBS.get(language, []))
    include_globs.extend(sorted(metadata_globs))
    if include_sql:
        include_globs.extend(SQL_INCLUDE_GLOBS)
    else:
        include_globs = [glob for glob in include_globs if glob not in SQL_INCLUDE_GLOBS]

    return {
        "include_globs": _dedupe(include_globs),
        "language_hints": sorted(languages),
        "metadata_globs": sorted(metadata_globs),
        "fallback_used": fallback_used,
    }


def _repo_roots_from_config(wiki_root: Path) -> list[str]:
    repos_path = wiki_root / "Wiki" / "_meta" / "repo_sync" / "repos.json"
    try:
        data = json.loads(repos_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    roots: list[str] = []
    for repo in data.get("repos") or []:
        root = str(repo.get("repoRoot") or "").strip()
        if root:
            roots.append(root)
    return roots


def _registry_source_roots(wiki_root: Path) -> list[str]:
    try:
        data = json.loads(DEFAULT_WIKI_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    roots: list[str] = []
    current = str(wiki_root.resolve())
    for item in data.get("roots") or []:
        if not isinstance(item, dict):
            continue
        try:
            item_root = str(Path(str(item.get("wiki_root") or "")).expanduser().resolve())
        except OSError:
            continue
        source_root = str(item.get("source_root") or "").strip()
        if item_root == current and source_root:
            roots.append(source_root)
    return roots


def _allowed_source_roots(wiki_root: Path) -> list[Path]:
    raw_roots = _registry_source_roots(wiki_root) or [str(DISPATCH_ROOT)]
    roots: list[Path] = []
    seen: set[str] = set()
    for raw in raw_roots:
        try:
            root = Path(raw).expanduser().resolve()
        except OSError:
            continue
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        roots.append(root)
    return roots or [DISPATCH_ROOT.resolve()]


def _resolve_root(root_text: str, allowed_roots: list[Path]) -> Path | None:
    try:
        root = Path(root_text).expanduser()
        if not root.is_absolute():
            root = allowed_roots[0] / root
        root = root.resolve()
    except OSError:
        return None
    for allowed_root in allowed_roots:
        if root == allowed_root or allowed_root in root.parents:
            return root
    return None


def resolve_search_roots(wiki_root: Path, roots: list[str] | None = None) -> tuple[list[Path], list[str]]:
    errors: list[str] = []
    allowed_roots = _allowed_source_roots(wiki_root)
    raw_roots = roots or _repo_roots_from_config(wiki_root) or [str(root) for root in allowed_roots] or FALLBACK_ROOTS
    resolved: list[Path] = []
    seen: set[str] = set()
    for raw in raw_roots:
        root = _resolve_root(str(raw), allowed_roots)
        if root is None:
            errors.append(f"root outside allowed source tree: {raw}")
            continue
        if not root.exists():
            errors.append(f"root does not exist: {root}")
            continue
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(root)
    return resolved, errors


def _grep_binary() -> str | None:
    if GREP_BIN.exists():
        return str(GREP_BIN)
    return shutil.which("grep")


def _grep_args(pattern: str, root: Path, *, regex: bool, include_globs: list[str]) -> list[str]:
    args = [
        _grep_binary() or "grep",
        "-RInI",
        "-E" if regex else "-F",
    ]
    for glob in include_globs:
        args.append(f"--include={glob}")
    for directory in DEFAULT_EXCLUDE_DIRS:
        args.append(f"--exclude-dir={directory}")
    args.extend(["--", pattern, str(root)])
    return args


def _parse_grep_line(line: str) -> tuple[str, int, str] | None:
    parts = line.rstrip("\n").split(":", 2)
    if len(parts) != 3 or not parts[1].isdigit():
        return None
    return parts[0], int(parts[1]), parts[2]


def _run_grep(
    pattern: str,
    root: Path,
    *,
    regex: bool,
    include_globs: list[str],
    remaining_limit: int,
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    grep = _grep_binary()
    if not grep:
        return [], False, "grep is not available"

    started = time.monotonic()
    proc = subprocess.Popen(
        _grep_args(pattern, root, regex=regex, include_globs=include_globs),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    selector = selectors.DefaultSelector()
    assert proc.stdout is not None
    selector.register(proc.stdout, selectors.EVENT_READ)

    matches: list[dict[str, Any]] = []
    truncated = False
    error: str | None = None
    timed_out = False

    while True:
        if len(matches) >= remaining_limit:
            truncated = True
            proc.terminate()
            break
        if time.monotonic() - started > timeout_seconds:
            timed_out = True
            proc.terminate()
            break
        if proc.poll() is not None:
            break

        events = selector.select(timeout=0.2)
        for key, _ in events:
            line = key.fileobj.readline()
            if not line:
                continue
            parsed = _parse_grep_line(line)
            if not parsed:
                continue
            path, line_number, text = parsed
            matches.append(
                {
                    "pattern": pattern,
                    "path": path,
                    "line": line_number,
                    "text": text[:500],
                }
            )
            if len(matches) >= remaining_limit:
                truncated = True
                proc.terminate()
                break

    try:
        _, stderr = proc.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, stderr = proc.communicate(timeout=2)
    finally:
        selector.close()

    if timed_out:
        error = f"grep timed out after {timeout_seconds:.0f}s for pattern '{pattern}' under {root}"
    elif proc.returncode not in (0, 1, -15) and not matches:
        error = (stderr or f"grep failed with exit code {proc.returncode}").strip()

    return matches, truncated, error


def _path_is_excluded(path: Path) -> bool:
    return any(part in DEFAULT_EXCLUDE_DIRS for part in path.parts)


def _read_utf16_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw.startswith(UTF16_BOMS):
        return None
    try:
        return raw.decode("utf-16")
    except UnicodeError:
        return None


def _run_utf16_sql_scan(
    pattern: str,
    root: Path,
    *,
    regex: bool,
    remaining_limit: int,
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """Supplement grep for SQL Server schema files exported as UTF-16.

    GNU grep with ``-I`` intentionally skips binary-looking files, and SQL
    Server schema dumps often have UTF-16 BOMs. Without this pass, important
    table/SP evidence can look absent even when it is present in ``*.sql``.
    """
    started = time.monotonic()
    matches: list[dict[str, Any]] = []
    truncated = False
    compiled: re.Pattern[str] | None = None
    if regex:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            return [], False, f"invalid regex for UTF-16 SQL scan: {exc}"

    try:
        sql_files = root.rglob("*.sql")
        for path in sql_files:
            if len(matches) >= remaining_limit:
                truncated = True
                break
            if time.monotonic() - started > timeout_seconds:
                return matches, truncated, f"UTF-16 SQL scan timed out after {timeout_seconds:.0f}s for pattern '{pattern}' under {root}"
            if _path_is_excluded(path):
                continue
            text = _read_utf16_text(path)
            if text is None:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if compiled.search(line) if compiled is not None else pattern in line:
                    matches.append(
                        {
                            "pattern": pattern,
                            "path": str(path),
                            "line": line_number,
                            "text": line[:500],
                            "encoding": "utf-16",
                        }
                    )
                    if len(matches) >= remaining_limit:
                        truncated = True
                        break
    except OSError as exc:
        return matches, truncated, f"UTF-16 SQL scan failed under {root}: {exc}"

    return matches, truncated, None


def search_source(
    *,
    wiki_root: Path,
    query: str = "",
    patterns: list[str] | None = None,
    roots: list[str] | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    regex: bool = False,
    include_sql: bool = False,
    timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    clean_patterns = _dedupe([p.strip() for p in (patterns or []) if p.strip()])
    if not clean_patterns and query.strip():
        clean_patterns = [query.strip()]
    if not clean_patterns:
        return _json_error("no search patterns provided", query=query, patterns=[])

    limit = max(1, min(int(limit), 200))
    wiki_root = wiki_root.resolve()
    search_roots, errors = resolve_search_roots(wiki_root, roots)
    allowed_roots = [str(root) for root in _allowed_source_roots(wiki_root)]
    include_profile = _include_profile(wiki_root, include_sql=include_sql)
    include_globs = include_profile["include_globs"]
    if not search_roots:
        result = _json_error("no valid source roots", query=query, patterns=clean_patterns)
        result["errors"].extend(errors)
        result["search_contract"] = {
            "include_globs": include_globs,
            "include_profile": include_profile,
            "include_sql": include_sql,
            "allowed_source_roots": allowed_roots,
        }
        return result

    matches: list[dict[str, Any]] = []
    truncated = False
    for pattern in clean_patterns:
        if len(matches) >= limit:
            truncated = True
            break
        for root in search_roots:
            if len(matches) >= limit:
                truncated = True
                break
            found, did_truncate, error = _run_grep(
                pattern,
                root,
                regex=regex,
                include_globs=include_globs,
                remaining_limit=limit - len(matches),
                timeout_seconds=timeout_seconds,
            )
            matches.extend(found)
            truncated = truncated or did_truncate
            if error:
                errors.append(error)
            if len(matches) >= limit:
                truncated = True
                break
            if include_sql:
                found, did_truncate, error = _run_utf16_sql_scan(
                    pattern,
                    root,
                    regex=regex,
                    remaining_limit=limit - len(matches),
                    timeout_seconds=timeout_seconds,
                )
                matches.extend(found)
                truncated = truncated or did_truncate
                if error:
                    errors.append(error)

    return {
        "query": query,
        "patterns": clean_patterns,
        "roots": [str(root) for root in search_roots],
        "matches": matches,
        "total_count": len(matches),
        "truncated": truncated,
        "errors": errors,
        "searched_at": _now_iso(),
        "limit_policy": {
            "default_limit": DEFAULT_SEARCH_LIMIT,
            "expanded_limit": EXPANDED_SEARCH_LIMIT,
            "expand_when": (
                "Only raise --limit after the first pass returns relevant but incomplete evidence; "
                "for broad/common patterns, refine roots or patterns before expanding."
            ),
        },
        "search_contract": {
            "engine": _grep_binary() or "grep",
            "fixed_string_default": not regex,
            "include_globs": include_globs,
            "include_profile": include_profile,
            "include_sql": include_sql,
            "multi_keyword_strategy": "one grep call per pattern",
            "semantic_expansion": "none; caller must provide explicit patterns",
            "utf16_sql_scan": "enabled only when include_sql=true",
            "allowed_source_roots": allowed_roots,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic source search for LLM Wiki queries")
    parser.add_argument("--wiki-root", default=".", help="Path to llm-wiki root")
    parser.add_argument("--query", default="", help="Legacy literal pattern used only when --pattern is absent")
    parser.add_argument("--pattern", action="append", default=[], help="Fixed-string search pattern; may repeat")
    parser.add_argument("--root", action="append", default=[], help="Source root under the selected wiki registry source_root; may repeat")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_SEARCH_LIMIT,
        help=(
            f"Maximum total matches (default {DEFAULT_SEARCH_LIMIT}; use "
            f"{EXPANDED_SEARCH_LIMIT} only after a relevant but incomplete first pass)"
        ),
    )
    parser.add_argument("--regex", action="store_true", help="Use grep -E instead of fixed-string grep -F")
    parser.add_argument(
        "--include-sql",
        action="store_true",
        help="Opt in to *.sql and UTF-16 SQL schema scans; default searches source code/config only.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args(argv)

    result = search_source(
        wiki_root=Path(args.wiki_root),
        query=args.query,
        patterns=args.pattern,
        roots=args.root,
        limit=args.limit,
        regex=args.regex,
        include_sql=args.include_sql,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"matches: {result['total_count']}")
        for match in result["matches"]:
            print(f"{match['path']}:{match['line']}:{match['text']}")
        if result["errors"]:
            print("errors:")
            for error in result["errors"]:
                print(f"- {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
