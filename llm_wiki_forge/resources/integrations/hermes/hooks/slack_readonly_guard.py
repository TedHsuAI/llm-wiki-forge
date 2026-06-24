#!/usr/bin/env python3
"""Query-only guard for Hermes Slack tool calls.

The Slack bot should be powerful enough to inspect code and generated evidence,
but it must not mutate files, repos, services, or scheduled jobs.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path


HERMES_HOME = Path("/home/tedhsu/.hermes")
SESSIONS_DIR = HERMES_HOME / "sessions"
LLM_WIKI_ROOT = Path("/home/tedhsu/.hermes/data/llm-wiki")
HERMES_VENV_PYTHON = Path("/home/tedhsu/.hermes/hermes-agent/venv/bin/python")
DISPATCH_SOURCE_ROOT = Path("/home/tedhsu/DispatchRawdata")
SYSTEM_VARIABLE_SCRIPT = Path(
    "/home/tedhsu/.hermes/skills/tgds-system-variable-setting/scripts/get_system_variable_setting.py"
)

BLOCKED_TOOLS = {
    "write_file",
    "patch",
    "process",
    "cronjob",
    "image_generate",
    "browser_click",
    "browser_type",
    "browser_press",
    "skill_manage",
    "todo_write",
}
SLACK_INTERNAL_SEARCH_TOOLS = {
    "search_files",
    "mcp_filesystem_search_files",
}

WRITE_RE = re.compile(
    r"""
    (?:^|[;&|]\s*)
    (?:
        rm|rmdir|mv|cp|install|touch|mkdir|chmod|chown|chgrp|truncate|tee|
        nano|vim|vi|ed|python\s+-m\s+pip|pip|npm|pnpm|yarn|uv\s+pip
    )\b
    |
    (?<![<])>{1,2}(?!&)
    |
    \b(?:sed|perl)\s+-[^\s]*i\b
    |
    \bfind\b[^\n]*(?:-delete|-exec\s+(?:rm|mv|cp|chmod|chown)\b)
    |
    \bgit\s+(?:reset|clean|push|commit|merge|rebase|checkout|switch|apply|am|stash\s+(?:pop|apply|drop|clear))\b
    |
    \b(?:systemctl|service|hermes\s+gateway)\s+(?:stop|restart|disable|enable|start|reload)\b
    |
    \b(?:kill|killall|pkill)\b
    |
    \b(?:drop\s+table|drop\s+database|delete\s+from|truncate\s+table)\b
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)

PY_WRITE_RE = re.compile(
    r"""
    \b(?:open|Path\s*\([^)]*\)\.open)\s*\([^)]*['"][wa+x]['"]
    |
    \b(?:write|write_text|write_bytes|writelines|touch|unlink|remove|rmdir|rmtree|rename|replace|mkdir|makedirs|chmod|chown)\s*\(
    |
    \b(?:subprocess|os\.system|os\.popen)\b
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)

READ_COMMANDS = {
    "awk",
    "cat",
    "cut",
    "df",
    "du",
    "file",
    "find",
    "git",
    "grep",
    "head",
    "jq",
    "less",
    "ls",
    "nl",
    "pwd",
    "rg",
    "sed",
    "sort",
    "stat",
    "tail",
    "tree",
    "uniq",
    "wc",
}

READ_GIT_SUBCOMMANDS = {
    "blame",
    "branch",
    "diff",
    "grep",
    "log",
    "ls-files",
    "rev-parse",
    "show",
    "status",
}

QUERY_RUNTIME_MODULES = {
    "scripts.query_runtime.graph_runtime": {
        "with_values": {"--wiki-root", "--question", "--top", "--extract-limit"},
        "without_values": {"--extract"},
    },
    "scripts.query_runtime.query_orchestrator": {
        "with_values": {"--wiki-root", "--question", "--top", "--extract-limit"},
        "without_values": {"--json"},
    },
    "scripts.query_runtime.source_search": {
        "with_values": {"--wiki-root", "--query", "--pattern", "--root", "--limit"},
        "without_values": {"--json", "--regex"},
    },
}


def block(message: str) -> None:
    print(json.dumps({"action": "block", "message": message}, ensure_ascii=False))


def session_platform(session_id: str) -> str:
    if not session_id:
        return ""
    candidates = [
        SESSIONS_DIR / f"{session_id}.json",
        SESSIONS_DIR / f"session_{session_id}.json",
    ]
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        return str(data.get("platform") or "").lower()
    return ""


def split_command(command: str) -> list[str]:
    # Keep shell separators out of quoted text while the write denylist still
    # scans the full command before this read-only allowlist runs.
    return [
        part.strip()
        for part in re.split(r"\s*(?:\|\||&&|\|)\s*", command)
        if part.strip()
    ]


def first_word(part: str) -> str:
    try:
        words = shlex.split(part, posix=True)
    except ValueError:
        words = part.split()
    if not words:
        return ""
    word = Path(words[0]).name.lower()
    return word


def git_is_read_only(part: str) -> bool:
    try:
        words = shlex.split(part, posix=True)
    except ValueError:
        words = part.split()
    if len(words) < 2:
        return False
    sub = words[1].lower()
    if sub == "branch" and any(arg in {"-d", "-D", "--delete"} for arg in words[2:]):
        return False
    return sub in READ_GIT_SUBCOMMANDS


def python_is_read_only(part: str) -> bool:
    if not re.search(r"\bpython3?\s+-[^\s]*c\b", part):
        return False
    return PY_WRITE_RE.search(part) is None


def path_matches_llm_wiki_root(path_text: str, *, cwd_is_wiki_root: bool) -> bool:
    if path_text in {".", "./"}:
        return cwd_is_wiki_root
    try:
        path = Path(path_text)
        if not path.is_absolute():
            path = LLM_WIKI_ROOT / path
        return path.resolve() == LLM_WIKI_ROOT.resolve()
    except OSError:
        return False


def path_matches_dispatch_source_root(path_text: str) -> bool:
    try:
        path = Path(path_text)
        if not path.is_absolute():
            path = DISPATCH_SOURCE_ROOT / path
        path = path.resolve()
        source_root = DISPATCH_SOURCE_ROOT.resolve()
        return path == source_root or source_root in path.parents
    except OSError:
        return False


def _bounded_integer(value: str, *, upper: int) -> bool:
    return value.isdigit() and 1 <= int(value) <= upper


def query_runtime_is_read_only_part(part: str, *, cwd_is_wiki_root: bool) -> bool:
    try:
        words = shlex.split(part, posix=True)
    except ValueError:
        return False
    if len(words) < 4:
        return False

    executable = Path(words[0])
    executable_name = executable.name.lower()
    if executable_name not in {"python", "python3"} and executable != HERMES_VENV_PYTHON:
        return False
    if words[1] != "-m":
        return False
    module_name = words[2]
    module_policy = QUERY_RUNTIME_MODULES.get(module_name)
    if not module_policy:
        return False
    flags_with_values = module_policy["with_values"]
    flags_without_values = module_policy["without_values"]

    seen_wiki_root = False
    args = words[3:]
    index = 0
    while index < len(args):
        flag = args[index]
        if flag in flags_without_values:
            index += 1
            continue
        if flag not in flags_with_values:
            return False
        if index + 1 >= len(args):
            return False
        value = args[index + 1]
        if flag == "--wiki-root":
            if not path_matches_llm_wiki_root(value, cwd_is_wiki_root=cwd_is_wiki_root):
                return False
            seen_wiki_root = True
        elif flag in {"--top", "--extract-limit"}:
            if not _bounded_integer(value, upper=20):
                return False
        elif flag == "--limit":
            if not _bounded_integer(value, upper=200):
                return False
        elif flag == "--root":
            if module_name != "scripts.query_runtime.source_search":
                return False
            if not path_matches_dispatch_source_root(value):
                return False
        index += 2

    return seen_wiki_root


def system_variable_lookup_is_read_only(command: str) -> bool:
    parts = split_command(command)
    if len(parts) != 1:
        return False
    try:
        words = shlex.split(parts[0], posix=True)
    except ValueError:
        return False
    if len(words) < 6:
        return False

    executable = Path(words[0])
    executable_name = executable.name.lower()
    if executable_name not in {"python", "python3"} and executable != HERMES_VENV_PYTHON:
        return False
    try:
        script = Path(words[1]).resolve()
    except OSError:
        return False
    if script != SYSTEM_VARIABLE_SCRIPT:
        return False

    seen_group = False
    seen_key = False
    args = words[2:]
    index = 0
    while index < len(args):
        flag = args[index]
        if flag == "--json":
            index += 1
            continue
        if flag not in {"--var-group", "--var-key", "--timeout"}:
            return False
        if index + 1 >= len(args):
            return False
        value = args[index + 1]
        if flag == "--var-group":
            seen_group = bool(value.strip())
        elif flag == "--var-key":
            seen_key = bool(value.strip())
        elif flag == "--timeout":
            try:
                timeout = float(value)
            except ValueError:
                return False
            if not 1.0 <= timeout <= 60.0:
                return False
        index += 2
    return seen_group and seen_key


def llm_wiki_query_runtime_is_read_only(command: str) -> bool:
    parts = split_command(command)
    if len(parts) == 1:
        return query_runtime_is_read_only_part(parts[0], cwd_is_wiki_root=False)
    if len(parts) != 2:
        return False

    try:
        cd_words = shlex.split(parts[0], posix=True)
    except ValueError:
        return False
    if len(cd_words) != 2 or cd_words[0] != "cd":
        return False
    if not path_matches_llm_wiki_root(cd_words[1], cwd_is_wiki_root=False):
        return False
    return query_runtime_is_read_only_part(parts[1], cwd_is_wiki_root=True)


def forge_code_cli_is_read_only_part(part: str, *, cwd_is_wiki_root: bool) -> bool:
    try:
        words = shlex.split(part, posix=True)
    except ValueError:
        return False
    if len(words) < 5:
        return False
    executable = Path(words[0])
    executable_name = executable.name.lower()
    if executable_name not in {"python", "python3"} and executable != HERMES_VENV_PYTHON:
        return False
    if words[1:4] != ["-m", "llm_wiki_forge", "code"]:
        return False
    subcommand = words[4]
    if subcommand not in {"query", "source-search"}:
        return False

    query_flags_with_values = {"--wiki-root", "--question", "--top", "--extract-limit", "--detail", "--reuse-days", "--max-shards"}
    source_flags_with_values = {"--wiki-root", "--pattern", "--root", "--limit", "--detail"}
    flags_without_values = {"--json", "--reuse-recent", "--no-reuse-recent"}
    flags_with_values = query_flags_with_values if subcommand == "query" else source_flags_with_values

    seen_wiki_root = False
    args = words[5:]
    index = 0
    while index < len(args):
        flag = args[index]
        if flag in flags_without_values:
            if subcommand != "query" and flag in {"--reuse-recent", "--no-reuse-recent"}:
                return False
            index += 1
            continue
        if flag not in flags_with_values:
            return False
        if index + 1 >= len(args):
            return False
        value = args[index + 1]
        if flag == "--wiki-root":
            if not path_matches_llm_wiki_root(value, cwd_is_wiki_root=cwd_is_wiki_root):
                return False
            seen_wiki_root = True
        elif flag in {"--top", "--extract-limit", "--reuse-days", "--max-shards"}:
            if not _bounded_integer(value, upper=30):
                return False
        elif flag == "--limit":
            if not _bounded_integer(value, upper=200):
                return False
        elif flag == "--root":
            if subcommand != "source-search" or not path_matches_dispatch_source_root(value):
                return False
        elif flag == "--detail":
            if value not in {"compact", "full"}:
                return False
        index += 2
    return seen_wiki_root


def llm_wiki_forge_code_cli_is_read_only(command: str) -> bool:
    parts = split_command(command)
    if len(parts) == 1:
        return forge_code_cli_is_read_only_part(parts[0], cwd_is_wiki_root=False)
    if len(parts) != 2:
        return False
    try:
        cd_words = shlex.split(parts[0], posix=True)
    except ValueError:
        return False
    if len(cd_words) != 2 or cd_words[0] != "cd":
        return False
    if not path_matches_llm_wiki_root(cd_words[1], cwd_is_wiki_root=False):
        return False
    return forge_code_cli_is_read_only_part(parts[1], cwd_is_wiki_root=True)


def terminal_is_query_only(command: str) -> bool:
    if WRITE_RE.search(command):
        return False
    if llm_wiki_query_runtime_is_read_only(command):
        return True
    if llm_wiki_forge_code_cli_is_read_only(command):
        return True
    if system_variable_lookup_is_read_only(command):
        return True
    for part in split_command(command):
        word = first_word(part)
        if word not in READ_COMMANDS:
            return False
        if word == "git" and not git_is_read_only(part):
            return False
        if word == "sed" and not re.search(r"\bsed\s+-n\b", part):
            return False
        if word == "find" and re.search(r"\b-(?:delete|exec|ok)\b", part):
            return False
    return True


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    if session_platform(str(payload.get("session_id") or "")) != "slack":
        return 0

    tool = str(payload.get("tool_name") or "").strip()
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}

    if tool in BLOCKED_TOOLS:
        block(f"Slack Hermes is query-only: tool '{tool}' is blocked to prevent modifications.")
        return 0

    if tool in SLACK_INTERNAL_SEARCH_TOOLS:
        block(
            "Slack Hermes code search must use llm-wiki-query: run query_orchestrator first, "
            "then source_search with explicit fixed-string patterns if semantic expansion is needed. "
            "Do not expose this internal tool routing block to the user."
        )
        return 0

    if tool == "memory":
        action = str(tool_input.get("action") or "").strip().lower()
        if action in {"add", "replace", "remove"}:
            block(
                "Slack Hermes is query-only: memory writes are blocked. "
                "Use Codex/local admin mode if this should become durable memory."
            )
            return 0

    if tool == "terminal":
        command = str(tool_input.get("command") or tool_input.get("cmd") or "").strip()
        if command and not terminal_is_query_only(command):
            block(
                "Slack Hermes is query-only: this terminal command is not on the "
                "read-only allowlist. Use read/search commands such as cat, rg, "
                "grep, find, sed -n, git show, git diff, or the fixed llm-wiki "
                "query_orchestrator/source_search commands; for system parameters, "
                "use the fixed tgds-system-variable-setting helper."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
