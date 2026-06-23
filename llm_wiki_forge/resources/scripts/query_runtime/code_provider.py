from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from tree_sitter import Language, Node, Parser

try:
    import tree_sitter_c_sharp
except ImportError:  # pragma: no cover - dependency availability is runtime-specific.
    tree_sitter_c_sharp = None

try:
    import tree_sitter_kotlin
except ImportError:  # pragma: no cover - optional Android dependency.
    tree_sitter_kotlin = None

try:
    import tree_sitter_java
except ImportError:  # pragma: no cover - optional Android dependency.
    tree_sitter_java = None

from .io import load_json
from .router import tokenize


BLOCKED_PARTS = {
    ".git",
    ".vs",
    "bin",
    "obj",
    "node_modules",
    "packages",
    "testresults",
    "coverage",
    "dist",
    "build",
}

DECLARATION_TYPES = {
    "annotation_type_declaration": "annotation",
    "class_declaration": "class",
    "companion_object": "object",
    "interface_declaration": "interface",
    "struct_declaration": "struct",
    "enum_declaration": "enum",
    "object_declaration": "object",
    "method_declaration": "method",
    "function_declaration": "method",
    "constructor_declaration": "constructor",
    "primary_constructor": "constructor",
    "secondary_constructor": "constructor",
    "property_declaration": "property",
    "field_declaration": "property",
    "record_declaration": "record",
}

PARSER_MODULES = {
    ".cs": tree_sitter_c_sharp,
    ".kt": tree_sitter_kotlin,
    ".kts": tree_sitter_kotlin,
    ".java": tree_sitter_java,
}

LARGE_METHOD_LINE_THRESHOLD = 300
LARGE_CLASS_LINE_THRESHOLD = 160
CHUNK_MAX_LINES = 140
CHUNK_OVERLAP_LINES = 8
MAX_CHUNKS_PER_SYMBOL = 4
CLASS_METHOD_FALLBACK_LIMIT = 3


def _load_path_variables(base_dir: Path | None) -> dict[str, str]:
    if base_dir is None:
        return {}
    scope_path = base_dir / "wiki.scope.json"
    if not scope_path.exists():
        return {}
    try:
        scope = load_json(scope_path)
    except Exception:
        return {}
    return {str(key): str(value) for key, value in (scope.get("pathVariables") or {}).items()}


def _expand_path_variables(path_text: str, base_dir: Path | None, path_variables: dict[str, str] | None) -> str:
    variables = path_variables if path_variables is not None else _load_path_variables(base_dir)
    expanded = path_text
    for key, value in variables.items():
        token = "${" + key + "}"
        if token not in expanded:
            continue
        root = Path(value) if len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"} else _path_from_wiki_metadata(value, base_dir, {})
        expanded = expanded.replace(token, str(root))
    if "${" in expanded:
        raise ValueError(f"Unresolved path variable in Hermes metadata path: {path_text}")
    return expanded


def _path_from_wiki_metadata(
    raw_path: str,
    base_dir: Path | None = None,
    path_variables: dict[str, str] | None = None,
) -> Path:
    path_text = str(raw_path or "").strip()
    if not path_text:
        return Path(path_text)

    was_variable_path = "${" in path_text
    path_text = _expand_path_variables(path_text, base_dir, path_variables)

    if len(path_text) >= 3 and path_text[1] == ":" and path_text[2] in {"\\", "/"}:
        return Path(path_text)

    if os.name != "nt" and path_text.startswith("/"):
        return Path(path_text.replace("\\", "/"))

    normalized = path_text.replace("\\", "/") if os.name != "nt" else path_text
    path = Path(normalized)
    if base_dir is not None and not path.is_absolute():
        return base_dir / path
    return path


@dataclass
class CodeEvidence:
    repo_id: str
    file_path: str
    symbol: str | None
    kind: str
    start_line: int
    end_line: int
    code: str
    extraction_method: str
    confidence: float
    parent_symbol: str | None = None
    chunk_index: int | None = None
    chunk_count: int | None = None
    chunk_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "repo_id": self.repo_id,
            "file_path": self.file_path,
            "symbol": self.symbol,
            "kind": self.kind,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "code": self.code,
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
        }
        if self.parent_symbol is not None:
            payload["parent_symbol"] = self.parent_symbol
        if self.chunk_index is not None:
            payload["chunk_index"] = self.chunk_index
        if self.chunk_count is not None:
            payload["chunk_count"] = self.chunk_count
        if self.chunk_hint is not None:
            payload["chunk_hint"] = self.chunk_hint
        return payload


class DynamicCodeProvider:
    def __init__(self, wiki_root: Path):
        self.wiki_root = wiki_root.resolve()
        self.scope = load_json(self.wiki_root / "wiki.scope.json")
        self.path_variables = {str(key): str(value) for key, value in (self.scope.get("pathVariables") or {}).items()}
        self.allowed_roots = self._load_allowed_roots()
        self.parsers: dict[str, Parser] = {}

    def _metadata_path(self, raw_path: str) -> Path:
        return _path_from_wiki_metadata(raw_path, self.wiki_root, self.path_variables)

    def _metadata_text(self, path: Path) -> str:
        resolved_path = path.resolve()
        for key, value in sorted(self.path_variables.items()):
            variable_root = (
                Path(value)
                if len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"}
                else _path_from_wiki_metadata(value, self.wiki_root, {})
            ).resolve()
            if resolved_path == variable_root or variable_root in resolved_path.parents:
                relative = os.path.relpath(resolved_path, variable_root).replace("\\", "/")
                if relative == ".":
                    return "${" + key + "}"
                return "${" + key + "}/" + relative
        if path.is_absolute():
            return os.path.relpath(path, self.wiki_root).replace("\\", "/")
        return str(path).replace("\\", "/")

    def _load_allowed_roots(self) -> list[Path]:
        roots: list[Path] = []
        for repo in self.scope.get("repos") or []:
            if repo.get("include"):
                actual_root = repo.get("actualRoot")
                if actual_root:
                    roots.append(self._metadata_path(actual_root).resolve())
            for target in repo.get("targets") or []:
                if target.get("include"):
                    actual_path = target.get("actualPath")
                    if actual_path:
                        roots.append(self._metadata_path(actual_path).resolve())
        # Keep longest first so child targets win diagnostics.
        return sorted(set(roots), key=lambda path: len(str(path)), reverse=True)

    def _resolve_safe_path(self, file_path: str) -> Path:
        path = self._metadata_path(file_path).resolve()
        lowered_parts = {part.lower() for part in path.parts}
        blocked = lowered_parts & BLOCKED_PARTS
        if blocked:
            raise ValueError(f"Refusing to read blocked path segment(s): {', '.join(sorted(blocked))}")
        if not path.exists():
            raise FileNotFoundError(str(path))
        if not any(path == root or root in path.parents for root in self.allowed_roots):
            raise ValueError(f"Refusing to read path outside wiki.scope.json whitelist: {path}")
        return path

    def _parser_for_path(self, path: Path) -> Parser | None:
        suffix = path.suffix.lower()
        parser_module = PARSER_MODULES.get(suffix)
        if parser_module is None:
            return None
        parser = self.parsers.get(suffix)
        if parser is None:
            parser = Parser(Language(parser_module.language()))
            self.parsers[suffix] = parser
        return parser

    def get_context(
        self,
        repo_id: str,
        file_paths: list[str],
        focus_symbols: list[str] | None = None,
        line_hints: list[dict[str, int]] | None = None,
        max_chars: int = 20000,
        max_symbols_per_file: int = 3,
        query: str = "",
    ) -> dict[str, Any]:
        evidence: list[CodeEvidence] = []
        errors: list[dict[str, str]] = []
        focus_symbols = focus_symbols or []
        line_hints = line_hints or []

        for raw_path in file_paths:
            try:
                path = self._resolve_safe_path(raw_path)
                source = path.read_text(encoding="utf-8-sig", errors="replace")
                if focus_symbols:
                    extracted = self._extract_symbols(repo_id, path, source, focus_symbols, max_chars, max_symbols_per_file, query)
                    evidence.extend(extracted)
                elif line_hints:
                    evidence.extend(self._extract_line_windows(repo_id, path, source, line_hints, max_chars))
                else:
                    evidence.append(self._extract_whole_or_head(repo_id, path, source, max_chars))
            except Exception as exc:  # Keep extraction errors in the evidence pack.
                errors.append({"file_path": raw_path, "error": str(exc)})

        for item in evidence:
            item.file_path = self._metadata_text(Path(item.file_path))

        return {
            "repo_id": repo_id,
            "code_evidence": [item.to_dict() for item in evidence],
            "errors": errors,
        }

    def _extract_symbols(
        self,
        repo_id: str,
        path: Path,
        source: str,
        focus_symbols: list[str],
        max_chars: int,
        max_symbols_per_file: int,
        query: str,
    ) -> list[CodeEvidence]:
        source_bytes = source.encode("utf-8")
        parser = self._parser_for_path(path)
        if parser is None:
            fallback = self._extract_whole_or_head(repo_id, path, source, max_chars)
            fallback.symbol = ", ".join(focus_symbols)
            fallback.kind = "symbol-unparsed"
            fallback.extraction_method = "tree-sitter-parser-unavailable"
            fallback.confidence = 0.35
            return [fallback]

        tree = parser.parse(source_bytes)
        declarations: list[tuple[str, str, Node]] = []
        self._collect_declarations(tree.root_node, [], declarations)

        normalized_focus = [self._normalize_symbol(symbol) for symbol in focus_symbols]
        evidence: list[CodeEvidence] = []
        matched_symbol_count = 0
        matched_declarations: list[tuple[str, str, Node]] = []
        used_nodes: set[int] = set()
        for focus in normalized_focus:
            for qualified_name, kind, node in declarations:
                if id(node) in used_nodes:
                    continue
                normalized_name = self._normalize_symbol(qualified_name)
                short_name = normalized_name.split(".")[-1]
                if not (focus == normalized_name or focus == short_name or focus.endswith(f".{short_name}")):
                    continue
                matched_declarations.append((qualified_name, kind, node))
                used_nodes.add(id(node))
                break

        if matched_declarations:
            method_fallbacks = self._method_fallbacks_for_matched_classes(
                repo_id=repo_id,
                path=path,
                source_bytes=source_bytes,
                declarations=declarations,
                matched_declarations=matched_declarations,
                query=query,
                max_chars=max_chars,
            )
            if method_fallbacks:
                return method_fallbacks

        for qualified_name, kind, node in matched_declarations:
            code = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            if kind == "method" and end_line - start_line + 1 > LARGE_METHOD_LINE_THRESHOLD:
                evidence.extend(
                    self._chunk_large_method(
                        repo_id=repo_id,
                        path=path,
                        qualified_name=qualified_name,
                        start_line=start_line,
                        code=code,
                        max_chars=max_chars,
                        query=query,
                    )
                )
                matched_symbol_count += 1
                if matched_symbol_count >= max_symbols_per_file:
                    break
                continue

            if len(code) > max_chars:
                code = code[:max_chars] + "\n/* truncated */"
            evidence.append(
                CodeEvidence(
                    repo_id=repo_id,
                    file_path=str(path),
                    symbol=qualified_name,
                    kind=kind,
                    start_line=start_line,
                    end_line=end_line,
                    code=code,
                    extraction_method="tree-sitter",
                    confidence=0.9,
                )
            )
            matched_symbol_count += 1
            if matched_symbol_count >= max_symbols_per_file:
                break

        if evidence:
            return evidence

        return [
            CodeEvidence(
                repo_id=repo_id,
                file_path=str(path),
                symbol=", ".join(focus_symbols),
                kind="symbol-index",
                start_line=1,
                end_line=1,
                code="\n".join(f"{kind}: {name}" for name, kind, _ in declarations[:200]),
                extraction_method="tree-sitter-symbol-index",
                confidence=0.45,
            )
        ]

    def _method_fallbacks_for_matched_classes(
        self,
        repo_id: str,
        path: Path,
        source_bytes: bytes,
        declarations: list[tuple[str, str, Node]],
        matched_declarations: list[tuple[str, str, Node]],
        query: str,
        max_chars: int,
    ) -> list[CodeEvidence]:
        tokens = set(tokenize(query))
        wants_logic = bool(tokens & {"邏輯", "api", "查詢", "付款", "payment", "fare", "bill", "車資", "dispatch", "派車", "batch", "cache", "排序", "rank"})
        if not wants_logic:
            return []

        class_nodes = [
            (qualified_name, node)
            for qualified_name, kind, node in matched_declarations
            if kind == "class" and node.end_point[0] - node.start_point[0] + 1 > LARGE_CLASS_LINE_THRESHOLD
        ]
        if not class_nodes:
            return []

        class_evidence: list[CodeEvidence] = []
        for class_name, class_node in class_nodes:
            child_methods = [
                (qualified_name, kind, node)
                for qualified_name, kind, node in declarations
                if kind == "method" and self._node_is_inside(node, class_node)
            ]
            ranked = self._rank_method_nodes(child_methods, query)
            for qualified_name, kind, node in ranked[:CLASS_METHOD_FALLBACK_LIMIT]:
                code = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                if end_line - start_line + 1 > LARGE_METHOD_LINE_THRESHOLD:
                    class_evidence.extend(
                        self._chunk_large_method(
                            repo_id=repo_id,
                            path=path,
                            qualified_name=qualified_name,
                            start_line=start_line,
                            code=code,
                            max_chars=max_chars,
                            query=query,
                        )
                    )
                    continue
                if len(code) > max_chars:
                    code = code[:max_chars] + "\n/* truncated */"
                class_evidence.append(
                    CodeEvidence(
                        repo_id=repo_id,
                        file_path=str(path),
                        symbol=qualified_name,
                        kind="method",
                        start_line=start_line,
                        end_line=end_line,
                        code=code,
                        extraction_method="tree-sitter-class-method-fallback",
                        confidence=0.84,
                        parent_symbol=class_name,
                    )
                )
        return class_evidence

    @staticmethod
    def _node_is_inside(node: Node, parent: Node) -> bool:
        return node.start_byte >= parent.start_byte and node.end_byte <= parent.end_byte and node is not parent

    def _rank_method_nodes(self, methods: list[tuple[str, str, Node]], query: str) -> list[tuple[str, str, Node]]:
        if not methods:
            return []
        tokens = set(tokenize(query))
        desired: set[str] = set(tokens)
        if tokens & {"付款", "payment", "pay", "bill"}:
            desired.update({"payment", "pay", "bill", "fubon", "tran"})
        if tokens & {"fare", "price", "車資", "小費"}:
            desired.update({"fare", "price", "meter", "taxi", "estimated"})
        if tokens & {"dispatch", "派車", "batch"}:
            desired.update({"dispatch", "batch", "job", "svc"})
        if tokens & {"rank", "排序", "cache", "快取"}:
            desired.update({"rank", "cache", "queue", "lookup"})

        def score(item: tuple[str, str, Node]) -> tuple[int, int]:
            qualified_name, _, node = item
            haystack = qualified_name.lower()
            matched = sum(1 for token in desired if token and token in haystack)
            return (matched, -node.start_point[0])

        ranked = sorted(methods, key=score, reverse=True)
        positive = [item for item in ranked if score(item)[0] > 0]
        return positive or ranked

    def _chunk_large_method(
        self,
        repo_id: str,
        path: Path,
        qualified_name: str,
        start_line: int,
        code: str,
        max_chars: int,
        query: str,
    ) -> list[CodeEvidence]:
        lines = code.splitlines()
        if not lines:
            return []

        windows: list[tuple[int, int]] = []
        cursor = 0
        while cursor < len(lines) and len(windows) < MAX_CHUNKS_PER_SYMBOL:
            end = min(len(lines), cursor + CHUNK_MAX_LINES)
            if end < len(lines):
                break_at = self._find_chunk_break(lines, cursor, end)
                if break_at > cursor:
                    end = break_at
            windows.append((cursor, end))
            if end >= len(lines):
                break
            cursor = max(end - CHUNK_OVERLAP_LINES, cursor + 1)

        chunks: list[CodeEvidence] = []
        total = len(windows)
        for index, (start, end) in enumerate(windows, start=1):
            chunk_code = "\n".join(lines[start:end])
            if len(chunk_code) > max_chars:
                chunk_code = chunk_code[:max_chars] + "\n/* truncated */"
            hint = self._infer_chunk_hint(chunk_code)
            chunks.append(
                CodeEvidence(
                    repo_id=repo_id,
                    file_path=str(path),
                    symbol=f"{qualified_name}#chunk{index}",
                    kind="method-chunk",
                    start_line=start_line + start,
                    end_line=start_line + end - 1,
                    code=chunk_code,
                    extraction_method="tree-sitter-large-method-chunk",
                    confidence=0.78,
                    parent_symbol=qualified_name,
                    chunk_index=index,
                    chunk_count=total,
                    chunk_hint=hint,
                )
            )
        return self._rank_chunks(chunks, query)

    @staticmethod
    def _find_chunk_break(lines: list[str], start: int, end: int) -> int:
        minimum = start + max(40, CHUNK_MAX_LINES // 2)
        markers = ("return ", "switch ", "case ", "if ", "else if ", "foreach ", "for ", "while ", "try", "catch", "#region", "#endregion")
        for index in range(end - 1, minimum, -1):
            stripped = lines[index].strip()
            if not stripped:
                return index + 1
            if stripped.startswith(markers):
                return index
        return end

    @staticmethod
    def _infer_chunk_hint(code: str) -> str:
        lowered = code.lower()
        hints: list[str] = []
        if "select " in lowered or "update " in lowered or "insert " in lowered or "delete " in lowered:
            hints.append("sql")
        if "switch " in lowered or "case " in lowered or "if " in lowered or "else if " in lowered:
            hints.append("branch")
        if "catch " in lowered or "throw " in lowered:
            hints.append("exception")
        if "return " in lowered:
            hints.append("return")
        if "region" in lowered:
            hints.append("region")
        return ",".join(hints) if hints else "method-slice"

    @staticmethod
    def _rank_chunks(chunks: list[CodeEvidence], query: str) -> list[CodeEvidence]:
        if not query:
            return chunks
        tokens = set(tokenize(query))
        desired: set[str] = set()
        if tokens & {"sql", "select", "查詢", "條件", "搜尋", "search"}:
            desired.add("sql")
        if tokens & {"條件", "判斷", "if", "switch", "branch"}:
            desired.add("branch")
        if tokens & {"例外", "錯誤", "error", "exception", "catch"}:
            desired.add("exception")
        if tokens & {"回傳", "return", "result", "結果"}:
            desired.add("return")
        if tokens & {"region", "區塊", "段落"}:
            desired.add("region")
        if not desired:
            return chunks

        def score(chunk: CodeEvidence) -> tuple[int, int]:
            hints = set((chunk.chunk_hint or "").split(","))
            matched = len(hints & desired)
            # Keep source order as a stable tiebreaker.
            return (matched, -(chunk.chunk_index or 0))

        ranked = sorted(chunks, key=score, reverse=True)
        # Preserve the original chunk_index; only output order changes.
        return ranked

    def _collect_declarations(
        self,
        node: Node,
        parents: list[str],
        declarations: list[tuple[str, str, Node]],
    ) -> None:
        kind = DECLARATION_TYPES.get(node.type)
        name = self._node_name(node)
        next_parents = parents
        if kind and name:
            qualified = ".".join([*parents, name])
            declarations.append((qualified, kind, node))
            if kind in {"class", "interface", "struct", "object", "enum", "record"}:
                next_parents = [*parents, name]
        for child in node.children:
            self._collect_declarations(child, next_parents, declarations)

    @staticmethod
    def _node_name(node: Node) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        return name_node.text.decode("utf-8", errors="replace")

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        symbol = symbol.replace("()", "")
        symbol = symbol.replace("::", ".")
        return symbol.strip().lower()

    def _extract_line_windows(
        self,
        repo_id: str,
        path: Path,
        source: str,
        line_hints: list[dict[str, int]],
        max_chars: int,
    ) -> list[CodeEvidence]:
        lines = source.splitlines()
        evidence: list[CodeEvidence] = []
        for hint in line_hints:
            start = max(1, int(hint.get("start_line", 1)) - 10)
            end = min(len(lines), int(hint.get("end_line", start)) + 20)
            code = "\n".join(lines[start - 1 : end])
            if len(code) > max_chars:
                code = code[:max_chars] + "\n/* truncated */"
            evidence.append(
                CodeEvidence(
                    repo_id=repo_id,
                    file_path=str(path),
                    symbol=None,
                    kind="line-window",
                    start_line=start,
                    end_line=end,
                    code=code,
                    extraction_method="line-window",
                    confidence=0.65,
                )
            )
        return evidence

    def _extract_whole_or_head(self, repo_id: str, path: Path, source: str, max_chars: int) -> CodeEvidence:
        code = source
        method = "whole-file"
        confidence = 0.7
        if len(code) > max_chars:
            code = code[:max_chars] + "\n/* truncated */"
            method = "file-head-truncated"
            confidence = 0.4
        return CodeEvidence(
            repo_id=repo_id,
            file_path=str(path),
            symbol=None,
            kind="file",
            start_line=1,
            end_line=code.count("\n") + 1,
            code=code,
            extraction_method=method,
            confidence=confidence,
        )
