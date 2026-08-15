"""Tree-sitter code graph extraction bound to immutable Git evidence."""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from multiprocessing import get_context
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid5

import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from threadline.git_repository import GitFile
from threadline.models import (
    CodeDependency,
    CodeParseDiagnostic,
    CodeSymbol,
    DependencyKind,
    Evidence,
    ParseStatus,
    RepositoryVersion,
    SymbolKind,
)

CODE_GRAPH_NAMESPACE = UUID("0e2d737e-976b-4b4c-8f6f-b1cb50ee838d")
LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}
DEFINITION_NODE_TYPES = {
    "class_declaration",
    "class_definition",
    "class_expression",
    "function_declaration",
    "function_definition",
    "method_definition",
    "variable_declarator",
}
CALL_NODE_TYPES = {"call", "call_expression", "new_expression"}
IMPORT_NODE_TYPES = {"import_from_statement", "import_statement"}
PARSE_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class CodeGraphExtraction:
    symbols: tuple[CodeSymbol, ...]
    dependencies: tuple[CodeDependency, ...]
    diagnostics: tuple[CodeParseDiagnostic, ...]


@dataclass(frozen=True)
class _ParsedSymbol:
    logical_key: str
    language: str
    path: str
    qualified_name: str
    symbol_kind: SymbolKind
    line_start: int
    line_end: int
    evidence_id: UUID


@dataclass(frozen=True)
class _ParsedDependency:
    source_symbol_key: str
    target_name: str
    dependency_kind: DependencyKind
    path: str
    line_start: int
    line_end: int
    evidence_id: UUID
    ordinal: int


@dataclass(frozen=True)
class _NodeView:
    node_type: str
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int
    has_error: bool
    is_missing: bool


@lru_cache(maxsize=4)
def _language(language: str) -> Language:
    """Keep each native grammar alive for every parser that references it."""

    return {
        "python": Language(tree_sitter_python.language()),
        "javascript": Language(tree_sitter_javascript.language()),
        "typescript": Language(tree_sitter_typescript.language_typescript()),
        "tsx": Language(tree_sitter_typescript.language_tsx()),
    }[language]


@lru_cache(maxsize=4)
def _parser(language: str) -> Parser:
    return Parser(_language(language))


def _module_name(path: str) -> str:
    source = Path(path)
    parts = list(source.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or source.stem


def _node_text(node: _NodeView, content: bytes) -> str:
    return content[node.start_byte : node.end_byte].decode("utf-8")


def _line_range(node: _NodeView) -> tuple[int, int]:
    return node.start_line, node.end_line


def _symbol_key(path: str, qualified_name: str) -> str:
    return f"symbol:{path}:{qualified_name}"


def _walk_nodes(root: Node) -> Iterator[_NodeView]:
    """Copy node facts before their TreeCursor advances native traversal state."""

    cursor = root.walk()
    reached_root = False
    while not reached_root:
        node = cursor.node
        if node is None:
            return
        if node.is_named or node.is_missing:
            view = _NodeView(
                node_type=node.type,
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                start_line=node.start_point.row + 1,
                end_line=node.end_point.row + 1,
                has_error=node.has_error,
                is_missing=node.is_missing,
            )
            del node
            yield view
        else:
            del node
        if cursor.goto_first_child():
            continue
        if cursor.goto_next_sibling():
            continue
        while True:
            if not cursor.goto_parent():
                reached_root = True
                break
            if cursor.goto_next_sibling():
                break


def _definition(
    node: _NodeView,
    *,
    language: str,
    scopes: tuple[_ParsedSymbol, ...],
    content: bytes,
) -> tuple[str, SymbolKind] | None:
    if node.has_error:
        return None
    source = " ".join(_node_text(node, content).split())
    if language == "python" and node.node_type == "class_definition":
        match = re.match(r"class\s+([A-Za-z_]\w*)", source)
        name = match.group(1) if match else None
        return (name, SymbolKind.CLASS) if name else None
    if language == "python" and node.node_type == "function_definition":
        match = re.match(r"(?:async\s+)?def\s+([A-Za-z_]\w*)", source)
        name = match.group(1) if match else None
        kind = (
            SymbolKind.METHOD
            if any(item.symbol_kind is SymbolKind.CLASS for item in scopes)
            else SymbolKind.FUNCTION
        )
        return (name, kind) if name else None
    if language != "python" and node.node_type in {"class_declaration", "class_expression"}:
        match = re.match(r"class\s+([A-Za-z_$][\w$]*)", source)
        name = match.group(1) if match else None
        return (name, SymbolKind.CLASS) if name else None
    if language != "python" and node.node_type == "function_declaration":
        match = re.match(r"(?:export\s+)?(?:async\s+)?function\s+\*?\s*([A-Za-z_$][\w$]*)", source)
        name = match.group(1) if match else None
        return (name, SymbolKind.FUNCTION) if name else None
    if language != "python" and node.node_type == "method_definition":
        match = re.match(r"(?:(?:static|async|get|set)\s+)*([A-Za-z_$][\w$]*)\s*\(", source)
        name = match.group(1) if match else None
        return (name, SymbolKind.METHOD) if name else None
    if language != "python" and node.node_type == "variable_declarator":
        match = re.match(r"([A-Za-z_$][\w$]*)\s*=", source)
        if match and ("=>" in source or re.search(r"=\s*(?:async\s+)?function", source)):
            return match.group(1), SymbolKind.FUNCTION
    return None


def _call_target(
    node: _NodeView, language: str, content: bytes
) -> tuple[str, DependencyKind] | None:
    if node.has_error:
        return None
    source = " ".join(_node_text(node, content).split())
    if language == "python" and node.node_type == "call":
        match = re.match(r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\(", source)
        target = match.group(1) if match else None
        if target is None:
            return None
        last = target.rsplit(".", 1)[-1]
        kind = DependencyKind.CONSTRUCTS if last[:1].isupper() else DependencyKind.CALLS
        return target, kind
    if language != "python" and node.node_type == "call_expression":
        match = re.match(r"([A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*)*)\s*\(", source)
        target = match.group(1) if match else None
        return (target, DependencyKind.CALLS) if target else None
    if language != "python" and node.node_type == "new_expression":
        match = re.match(r"new\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)", source)
        target = match.group(1) if match else None
        return (target, DependencyKind.CONSTRUCTS) if target else None
    return None


def _python_import_targets(node: _NodeView, content: bytes) -> tuple[str, ...]:
    source = " ".join(_node_text(node, content).split())
    if node.node_type == "import_from_statement":
        match = re.match(r"from\s+([.A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s+import\s+", source)
        module = match.group(1) if match else None
        return (module,) if module else ()
    imported = source.removeprefix("import ")
    return tuple(
        item.split(" as ", 1)[0].strip()
        for item in imported.split(",")
        if item.split(" as ", 1)[0].strip()
    )


def _import_targets(node: _NodeView, language: str, content: bytes) -> tuple[str, ...]:
    if node.has_error:
        return ()
    if language == "python" and node.node_type in {
        "import_statement",
        "import_from_statement",
    }:
        return _python_import_targets(node, content)
    if language != "python" and node.node_type == "import_statement":
        statement = _node_text(node, content)
        match = re.search(r"(?:from\s+)?(['\"])(.*?)\1\s*;?\s*$", statement, re.DOTALL)
        if match is None:
            return ()
        decoded = match.group(2)
        return (decoded,) if decoded else ()
    return ()


def _error_lines(root: Node) -> tuple[int, ...]:
    lines: set[int] = set()
    for node in _walk_nodes(root):
        if node.node_type == "ERROR" or node.is_missing:
            lines.add(node.start_line)
    return tuple(sorted(lines))


def _parse_file(
    git_file: GitFile,
    evidence: Evidence,
    language: str,
) -> tuple[list[_ParsedSymbol], list[_ParsedDependency], ParseStatus, tuple[int, ...]]:
    content = git_file.content.encode("utf-8")
    tree = _parser(language).parse(content)
    module_name = _module_name(git_file.path)
    module = _ParsedSymbol(
        logical_key=_symbol_key(git_file.path, module_name),
        language=language,
        path=git_file.path,
        qualified_name=module_name,
        symbol_kind=SymbolKind.MODULE,
        line_start=1,
        line_end=max(1, git_file.content.count("\n") + 1),
        evidence_id=evidence.id,
    )
    symbols = [module]
    dependencies: list[_ParsedDependency] = []
    ordinal = 0

    active_scopes: list[tuple[_ParsedSymbol, int]] = []
    for node in _walk_nodes(tree.root_node):
        while active_scopes and node.start_byte >= active_scopes[-1][1]:
            active_scopes.pop()
        if node.node_type == "ERROR" or node.is_missing:
            continue
        scopes = tuple(item[0] for item in active_scopes)
        definition = (
            _definition(node, language=language, scopes=scopes, content=content)
            if node.node_type in DEFINITION_NODE_TYPES
            else None
        )
        if definition is not None:
            name, symbol_kind = definition
            parents = [
                module.qualified_name,
                *(item.qualified_name.rsplit(".", 1)[-1] for item in scopes),
            ]
            qualified_name = ".".join((*parents, name))
            start, end = _line_range(node)
            symbol = _ParsedSymbol(
                logical_key=_symbol_key(git_file.path, qualified_name),
                language=language,
                path=git_file.path,
                qualified_name=qualified_name,
                symbol_kind=symbol_kind,
                line_start=start,
                line_end=end,
                evidence_id=evidence.id,
            )
            symbols.append(symbol)
            active_scopes.append((symbol, node.end_byte))

        owner = active_scopes[-1][0] if active_scopes else module
        import_targets = (
            _import_targets(node, language, content) if node.node_type in IMPORT_NODE_TYPES else ()
        )
        for target in import_targets:
            start, end = _line_range(node)
            dependencies.append(
                _ParsedDependency(
                    source_symbol_key=owner.logical_key,
                    target_name=target,
                    dependency_kind=DependencyKind.IMPORTS,
                    path=git_file.path,
                    line_start=start,
                    line_end=end,
                    evidence_id=evidence.id,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
        call = _call_target(node, language, content) if node.node_type in CALL_NODE_TYPES else None
        if call is not None:
            target, dependency_kind = call
            start, end = _line_range(node)
            dependencies.append(
                _ParsedDependency(
                    source_symbol_key=owner.logical_key,
                    target_name=target,
                    dependency_kind=dependency_kind,
                    path=git_file.path,
                    line_start=start,
                    line_end=end,
                    evidence_id=evidence.id,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
    errors = _error_lines(tree.root_node)
    status = ParseStatus.PARTIAL if tree.root_node.has_error else ParseStatus.COMPLETE
    return symbols, dependencies, status, errors


def _parse_file_worker(
    connection: Connection,
) -> None:  # pragma: no cover - coverage is owned by the isolated child process
    """Serve parser requests in one isolated process for the full indexing run."""

    error_sink = os.open(os.devnull, os.O_WRONLY)
    os.dup2(error_sink, 2)
    os.close(error_sink)
    try:
        while True:
            try:
                request = connection.recv()
            except EOFError:
                break
            if request == "close":
                connection.send(("closed", None))
                break
            git_file, evidence, language = cast(tuple[GitFile, Evidence, str], request)
            try:
                connection.send(("ok", _parse_file(git_file, evidence, language)))
            except Exception as exc:  # pragma: no cover - exercised across process boundary
                connection.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        connection.close()
    os._exit(0)


class _IsolatedParserSession:
    """Reuse one crash-isolated native parser instead of spawning once per file."""

    def __init__(self) -> None:
        self._connection: Connection | None = None
        self._process: Any | None = None

    def _start(self) -> None:
        context = get_context("spawn")
        receiver, sender = context.Pipe(duplex=True)
        process = context.Process(
            target=_parse_file_worker,
            args=(sender,),
            daemon=True,
        )
        process.start()
        sender.close()
        self._connection = receiver
        self._process = process

    def _stop(self) -> None:
        connection = self._connection
        process = self._process
        self._connection = None
        self._process = None
        if connection is not None:
            connection.close()
        if process is not None:
            process.join(timeout=1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)

    def parse(
        self,
        git_file: GitFile,
        evidence: Evidence,
        language: str,
    ) -> tuple[list[_ParsedSymbol], list[_ParsedDependency], ParseStatus, tuple[int, ...]]:
        if self._connection is None:
            self._start()
        connection = self._connection
        process = self._process
        if connection is None or process is None:
            raise RuntimeError("isolated parser did not start")
        try:
            connection.send((git_file, evidence, language))
            if not connection.poll(PARSE_TIMEOUT_SECONDS):
                raise TimeoutError(f"parser exceeded {PARSE_TIMEOUT_SECONDS} seconds")
            outcome, payload = connection.recv()
        except (BrokenPipeError, EOFError, OSError, TimeoutError) as error:
            exit_code = process.exitcode
            self._stop()
            if isinstance(error, TimeoutError):
                raise
            raise RuntimeError(
                f"native parser exited without a result (exit code {exit_code})"
            ) from error
        if outcome != "ok":
            raise RuntimeError(str(payload))
        return cast(
            tuple[list[_ParsedSymbol], list[_ParsedDependency], ParseStatus, tuple[int, ...]],
            payload,
        )

    def close(self) -> None:
        connection = self._connection
        process = self._process
        if connection is None or process is None:
            return
        try:
            connection.send("close")
            if connection.poll(1):
                connection.recv()
        except (BrokenPipeError, EOFError, OSError):
            pass
        self._stop()


def _parse_file_isolated(
    git_file: GitFile,
    evidence: Evidence,
    language: str,
) -> tuple[list[_ParsedSymbol], list[_ParsedDependency], ParseStatus, tuple[int, ...]]:
    """Parse one file in isolation; retained for focused callers and tests."""

    session = _IsolatedParserSession()
    try:
        return session.parse(git_file, evidence, language)
    finally:
        session.close()


def _identity(
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    repository_version: RepositoryVersion,
    task_id: UUID,
    logical_key: str,
) -> UUID:
    return uuid5(
        CODE_GRAPH_NAMESPACE,
        ":".join(
            (
                str(tenant_id),
                str(workspace_id),
                str(repository_version.repository_id),
                repository_version.branch,
                repository_version.commit_sha,
                str(task_id),
                logical_key,
            )
        ),
    )


def _resolve_target(
    dependency: _ParsedDependency,
    symbols_by_key: dict[str, _ParsedSymbol],
    simple_names: dict[str, list[_ParsedSymbol]],
    modules: dict[str, _ParsedSymbol],
) -> str | None:
    if dependency.dependency_kind is DependencyKind.IMPORTS:
        imported = dependency.target_name.lstrip(".")
        module = modules.get(imported)
        return module.logical_key if module is not None else None

    target_name = dependency.target_name.replace("?.", ".")
    simple = target_name.rsplit(".", 1)[-1]
    source = symbols_by_key[dependency.source_symbol_key]
    source_parts = source.qualified_name.split(".")
    if len(source_parts) >= 2:
        same_scope = ".".join((*source_parts[:-1], simple))
        for candidate in simple_names.get(simple, []):
            if candidate.qualified_name == same_scope:
                return candidate.logical_key
    candidates = simple_names.get(simple, [])
    if len(candidates) == 1:
        return candidates[0].logical_key
    return None


def _merge_logical_symbols(symbols: list[_ParsedSymbol]) -> list[_ParsedSymbol]:
    """Represent overloads and repeated declarations as one logical code symbol."""

    merged: dict[str, _ParsedSymbol] = {}
    for symbol in symbols:
        existing = merged.get(symbol.logical_key)
        if existing is None:
            merged[symbol.logical_key] = symbol
            continue
        merged[symbol.logical_key] = _ParsedSymbol(
            logical_key=symbol.logical_key,
            language=symbol.language,
            path=symbol.path,
            qualified_name=symbol.qualified_name,
            symbol_kind=symbol.symbol_kind,
            line_start=min(existing.line_start, symbol.line_start),
            line_end=max(existing.line_end, symbol.line_end),
            evidence_id=symbol.evidence_id,
        )
    return list(merged.values())


def _cached_parse(
    payload: object,
    *,
    evidence_id: UUID,
) -> tuple[list[_ParsedSymbol], list[_ParsedDependency], ParseStatus, tuple[int, ...]] | None:
    if not isinstance(payload, dict):
        return None

    def integer(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError("cached integer is malformed")
        return int(value)

    try:
        symbols = [
            _ParsedSymbol(
                logical_key=str(item["logical_key"]),
                language=str(item["language"]),
                path=str(item["path"]),
                qualified_name=str(item["qualified_name"]),
                symbol_kind=SymbolKind(str(item["symbol_kind"])),
                line_start=integer(item["line_start"]),
                line_end=integer(item["line_end"]),
                evidence_id=evidence_id,
            )
            for item in cast(list[dict[str, object]], payload["symbols"])
        ]
        dependencies = [
            _ParsedDependency(
                source_symbol_key=str(item["source_symbol_key"]),
                target_name=str(item["target_name"]),
                dependency_kind=DependencyKind(str(item["dependency_kind"])),
                path=str(item["path"]),
                line_start=integer(item["line_start"]),
                line_end=integer(item["line_end"]),
                evidence_id=evidence_id,
                ordinal=integer(item["ordinal"]),
            )
            for item in cast(list[dict[str, object]], payload["dependencies"])
        ]
        return (
            symbols,
            dependencies,
            ParseStatus(str(payload["status"])),
            tuple(integer(item) for item in cast(list[object], payload["error_lines"])),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _cache_payload(
    parsed: tuple[
        list[_ParsedSymbol],
        list[_ParsedDependency],
        ParseStatus,
        tuple[int, ...],
    ],
) -> dict[str, object]:
    symbols, dependencies, status, error_lines = parsed
    return {
        "symbols": [
            {
                "logical_key": item.logical_key,
                "language": item.language,
                "path": item.path,
                "qualified_name": item.qualified_name,
                "symbol_kind": item.symbol_kind.value,
                "line_start": item.line_start,
                "line_end": item.line_end,
            }
            for item in symbols
        ],
        "dependencies": [
            {
                "source_symbol_key": item.source_symbol_key,
                "target_name": item.target_name,
                "dependency_kind": item.dependency_kind.value,
                "path": item.path,
                "line_start": item.line_start,
                "line_end": item.line_end,
                "ordinal": item.ordinal,
            }
            for item in dependencies
        ],
        "status": status.value,
        "error_lines": list(error_lines),
    }


def extract_code_graph(
    files: tuple[GitFile, ...],
    evidence_by_path: dict[str, Evidence],
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_id: UUID,
    task_id: UUID,
    repository_version: RepositoryVersion,
    isolate_native: bool = True,
    cache_path: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> CodeGraphExtraction:
    """Parse supported committed files and return deterministic, evidence-bound entities."""

    parsed_symbols: list[_ParsedSymbol] = []
    parsed_dependencies: list[_ParsedDependency] = []
    parsed_diagnostics: list[tuple[str, str, ParseStatus, tuple[int, ...], UUID]] = []
    cached_entries: dict[str, object] = {}
    if cache_path is not None and cache_path.is_file():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("schema_version") == 1:
                raw_entries = payload.get("entries", {})
                if isinstance(raw_entries, dict):
                    cached_entries = raw_entries
        except (OSError, ValueError):
            cached_entries = {}
    retained_entries: dict[str, object] = {}
    supported = [
        item for item in files if LANGUAGE_BY_SUFFIX.get(Path(item.path).suffix.lower()) is not None
    ]
    parsed_count = 0
    reused_count = 0
    isolated_parser = _IsolatedParserSession() if isolate_native else None
    try:
        for git_file in sorted(files, key=lambda item: item.path):
            language = LANGUAGE_BY_SUFFIX.get(Path(git_file.path).suffix.lower())
            if language is None:
                continue
            evidence = evidence_by_path[git_file.path]
            cache_key = f"{language}:{git_file.path}:{git_file.content_hash}"
            parsed = _cached_parse(cached_entries.get(cache_key), evidence_id=evidence.id)
            if parsed is None:
                try:
                    parsed = (
                        isolated_parser.parse(git_file, evidence, language)
                        if isolated_parser is not None
                        else _parse_file(git_file, evidence, language)
                    )
                except Exception as exc:  # pragma: no cover - tested via injected boundary
                    parsed = ([], [], ParseStatus.FAILED, ())
                    _ = exc
                parsed_count += 1
                retained_entries[cache_key] = _cache_payload(parsed)
            else:
                reused_count += 1
                retained_entries[cache_key] = cached_entries[cache_key]
            file_symbols, file_dependencies, status, error_lines = parsed
            parsed_symbols.extend(file_symbols)
            parsed_dependencies.extend(file_dependencies)
            parsed_diagnostics.append((git_file.path, language, status, error_lines, evidence.id))
            completed = parsed_count + reused_count
            progress_interval = max(1, len(supported) // 10)
            if progress is not None and (
                completed == 1 or completed == len(supported) or completed % progress_interval == 0
            ):
                progress(
                    f"Indexed {completed}/{len(supported)} source files "
                    f"({parsed_count} parsed, {reused_count} reused)."
                )
    finally:
        if isolated_parser is not None:
            isolated_parser.close()

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"schema_version": 1, "entries": retained_entries}, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(cache_path)

    parsed_symbols = _merge_logical_symbols(parsed_symbols)
    symbol_by_key = {item.logical_key: item for item in parsed_symbols}
    simple_names: dict[str, list[_ParsedSymbol]] = defaultdict(list)
    modules: dict[str, _ParsedSymbol] = {}
    for symbol in parsed_symbols:
        simple_names[symbol.qualified_name.rsplit(".", 1)[-1]].append(symbol)
        if symbol.symbol_kind is SymbolKind.MODULE:
            modules[symbol.qualified_name] = symbol

    code_symbols = tuple(
        CodeSymbol(
            id=_identity(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                repository_version=repository_version,
                task_id=task_id,
                logical_key=item.logical_key,
            ),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            created_by=actor_id,
            repository_version=repository_version,
            task_id=task_id,
            logical_key=item.logical_key,
            language=item.language,
            path=item.path,
            qualified_name=item.qualified_name,
            symbol_kind=item.symbol_kind,
            line_start=item.line_start,
            line_end=item.line_end,
            evidence_id=item.evidence_id,
        )
        for item in sorted(parsed_symbols, key=lambda value: value.logical_key)
    )

    code_dependencies: list[CodeDependency] = []
    for item in parsed_dependencies:
        target_key = _resolve_target(item, symbol_by_key, simple_names, modules)
        logical_key = (
            f"dependency:{item.source_symbol_key}:{item.dependency_kind.value}:"
            f"{item.target_name}:{item.line_start}:{item.ordinal}"
        )
        code_dependencies.append(
            CodeDependency(
                id=_identity(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    repository_version=repository_version,
                    task_id=task_id,
                    logical_key=logical_key,
                ),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                created_by=actor_id,
                repository_version=repository_version,
                task_id=task_id,
                logical_key=logical_key,
                source_symbol_key=item.source_symbol_key,
                target_name=item.target_name,
                target_symbol_key=target_key,
                dependency_kind=item.dependency_kind,
                path=item.path,
                line_start=item.line_start,
                line_end=item.line_end,
                evidence_id=item.evidence_id,
            )
        )

    diagnostics = tuple(
        CodeParseDiagnostic(
            id=_identity(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                repository_version=repository_version,
                task_id=task_id,
                logical_key=f"parse:{path}",
            ),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            created_by=actor_id,
            repository_version=repository_version,
            task_id=task_id,
            logical_key=f"parse:{path}",
            language=language,
            path=path,
            status=status,
            error_lines=error_lines,
            message=(
                "Parsed complete syntax tree."
                if status is ParseStatus.COMPLETE
                else "Indexed only syntax outside Tree-sitter error nodes."
                if status is ParseStatus.PARTIAL
                else "Parser failed safely without emitting inferred code relationships."
            ),
            evidence_id=evidence_id,
        )
        for path, language, status, error_lines, evidence_id in parsed_diagnostics
    )
    return CodeGraphExtraction(
        symbols=code_symbols,
        dependencies=tuple(sorted(code_dependencies, key=lambda value: value.logical_key)),
        diagnostics=diagnostics,
    )
