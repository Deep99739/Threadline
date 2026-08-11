"""Tree-sitter code graph extraction bound to immutable Git evidence."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
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


@lru_cache(maxsize=4)
def _parser(language: str) -> Parser:
    grammar = {
        "python": Language(tree_sitter_python.language()),
        "javascript": Language(tree_sitter_javascript.language()),
        "typescript": Language(tree_sitter_typescript.language_typescript()),
        "tsx": Language(tree_sitter_typescript.language_tsx()),
    }[language]
    return Parser(grammar)


def _module_name(path: str) -> str:
    source = Path(path)
    parts = list(source.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or source.stem


def _node_text(node: Node, content: bytes) -> str:
    return content[node.start_byte : node.end_byte].decode("utf-8")


def _line_range(node: Node) -> tuple[int, int]:
    return node.start_point.row + 1, node.end_point.row + 1


def _symbol_key(path: str, qualified_name: str) -> str:
    return f"symbol:{path}:{qualified_name}"


def _named_child_text(node: Node, field: str, content: bytes) -> str | None:
    child = node.child_by_field_name(field)
    if child is None:
        return None
    value = " ".join(_node_text(child, content).split())
    return value or None


def _definition(
    node: Node,
    *,
    language: str,
    scopes: tuple[_ParsedSymbol, ...],
    content: bytes,
) -> tuple[str, SymbolKind] | None:
    if node.has_error:
        return None
    if language == "python" and node.type == "class_definition":
        name = _named_child_text(node, "name", content)
        return (name, SymbolKind.CLASS) if name else None
    if language == "python" and node.type == "function_definition":
        name = _named_child_text(node, "name", content)
        kind = (
            SymbolKind.METHOD
            if any(item.symbol_kind is SymbolKind.CLASS for item in scopes)
            else SymbolKind.FUNCTION
        )
        return (name, kind) if name else None
    if language != "python" and node.type in {"class_declaration", "class_expression"}:
        name = _named_child_text(node, "name", content)
        return (name, SymbolKind.CLASS) if name else None
    if language != "python" and node.type == "function_declaration":
        name = _named_child_text(node, "name", content)
        return (name, SymbolKind.FUNCTION) if name else None
    if language != "python" and node.type == "method_definition":
        name = _named_child_text(node, "name", content)
        return (name, SymbolKind.METHOD) if name else None
    if language != "python" and node.type == "variable_declarator":
        value = node.child_by_field_name("value")
        if value is not None and value.type in {
            "arrow_function",
            "function_expression",
            "generator_function",
        }:
            name = _named_child_text(node, "name", content)
            return (name, SymbolKind.FUNCTION) if name else None
    return None


def _call_target(node: Node, language: str, content: bytes) -> tuple[str, DependencyKind] | None:
    if node.has_error:
        return None
    if language == "python" and node.type == "call":
        target = _named_child_text(node, "function", content)
        if target is None:
            return None
        last = target.rsplit(".", 1)[-1]
        kind = DependencyKind.CONSTRUCTS if last[:1].isupper() else DependencyKind.CALLS
        return target, kind
    if language != "python" and node.type == "call_expression":
        target = _named_child_text(node, "function", content)
        return (target, DependencyKind.CALLS) if target else None
    if language != "python" and node.type == "new_expression":
        target = _named_child_text(node, "constructor", content)
        return (target, DependencyKind.CONSTRUCTS) if target else None
    return None


def _python_import_targets(node: Node, content: bytes) -> tuple[str, ...]:
    if node.type == "import_from_statement":
        module = _named_child_text(node, "module_name", content)
        return (module,) if module else ()
    targets: list[str] = []
    for index, child in enumerate(node.children):
        if node.field_name_for_child(index) != "name":
            continue
        name_node = child.child_by_field_name("name") if child.type == "aliased_import" else child
        if name_node is not None:
            targets.append(" ".join(_node_text(name_node, content).split()))
    return tuple(targets)


def _import_targets(node: Node, language: str, content: bytes) -> tuple[str, ...]:
    if node.has_error:
        return ()
    if language == "python" and node.type in {"import_statement", "import_from_statement"}:
        return _python_import_targets(node, content)
    if language != "python" and node.type == "import_statement":
        source = _named_child_text(node, "source", content)
        if source is None:
            return ()
        try:
            decoded = json.loads(source)
        except json.JSONDecodeError:
            return ()
        return (decoded,) if isinstance(decoded, str) and decoded else ()
    return ()


def _error_lines(root: Node) -> tuple[int, ...]:
    lines: set[int] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "ERROR" or node.is_missing:
            lines.add(node.start_point.row + 1)
            continue
        stack.extend(node.children)
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

    def visit(node: Node, scopes: tuple[_ParsedSymbol, ...]) -> None:
        nonlocal ordinal
        if node.type == "ERROR" or node.is_missing:
            return
        next_scopes = scopes
        definition = _definition(node, language=language, scopes=scopes, content=content)
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
            next_scopes = (*scopes, symbol)

        owner = next_scopes[-1] if next_scopes else module
        for target in _import_targets(node, language, content):
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
        call = _call_target(node, language, content)
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
        for child in node.named_children:
            visit(child, next_scopes)

    visit(tree.root_node, ())
    errors = _error_lines(tree.root_node)
    status = ParseStatus.PARTIAL if tree.root_node.has_error else ParseStatus.COMPLETE
    return symbols, dependencies, status, errors


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


def extract_code_graph(
    files: tuple[GitFile, ...],
    evidence_by_path: dict[str, Evidence],
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_id: UUID,
    task_id: UUID,
    repository_version: RepositoryVersion,
) -> CodeGraphExtraction:
    """Parse supported committed files and return deterministic, evidence-bound entities."""

    parsed_symbols: list[_ParsedSymbol] = []
    parsed_dependencies: list[_ParsedDependency] = []
    parsed_diagnostics: list[tuple[str, str, ParseStatus, tuple[int, ...], UUID]] = []
    for git_file in sorted(files, key=lambda item: item.path):
        language = LANGUAGE_BY_SUFFIX.get(Path(git_file.path).suffix.lower())
        if language is None:
            continue
        evidence = evidence_by_path[git_file.path]
        try:
            file_symbols, file_dependencies, status, error_lines = _parse_file(
                git_file, evidence, language
            )
        except Exception as exc:  # pragma: no cover - parser boundary is tested via injection
            file_symbols = []
            file_dependencies = []
            status = ParseStatus.FAILED
            error_lines = ()
            _ = exc
        parsed_symbols.extend(file_symbols)
        parsed_dependencies.extend(file_dependencies)
        parsed_diagnostics.append((git_file.path, language, status, error_lines, evidence.id))

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
        dependencies=tuple(
            sorted(code_dependencies, key=lambda value: value.logical_key)
        ),
        diagnostics=diagnostics,
    )
