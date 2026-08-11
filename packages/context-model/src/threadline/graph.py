"""Authorization-scoped, bounded traversal over the committed code graph."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from uuid import UUID

from threadline.models import Citation, CodeDependency, CodeSymbol, ContextSnapshot

MAX_GRAPH_DEPTH = 5
MAX_GRAPH_NODES = 100


@dataclass(frozen=True)
class CodeGraphTrace:
    root: CodeSymbol
    nodes: tuple[CodeSymbol, ...]
    dependencies: tuple[CodeDependency, ...]
    unresolved_dependencies: tuple[CodeDependency, ...]
    citations: tuple[Citation, ...]
    max_depth: int
    max_nodes: int
    truncated: bool


def _resolve_root(snapshot: ContextSnapshot, symbol: str) -> CodeSymbol:
    exact = [item for item in snapshot.code_symbols if item.logical_key == symbol]
    if exact:
        return exact[0]
    qualified = [item for item in snapshot.code_symbols if item.qualified_name == symbol]
    if not qualified:
        raise LookupError(f"Code symbol was not found: {symbol}")
    if len(qualified) > 1:
        raise ValueError(
            "Code symbol name is ambiguous; use the stable logical key: "
            + ", ".join(item.logical_key for item in qualified)
        )
    return qualified[0]


def trace_code_graph(
    snapshot: ContextSnapshot,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    symbol: str,
    max_depth: int = 2,
    max_nodes: int = 50,
) -> CodeGraphTrace:
    """Traverse resolved calls, construction, and imports without crossing scope or bounds."""

    if snapshot.tenant_id != tenant_id or snapshot.workspace_id != workspace_id:
        raise PermissionError("caller scope does not match the authorized context snapshot")
    if not 0 <= max_depth <= MAX_GRAPH_DEPTH:
        raise ValueError(f"max_depth must be between 0 and {MAX_GRAPH_DEPTH}")
    if not 1 <= max_nodes <= MAX_GRAPH_NODES:
        raise ValueError(f"max_nodes must be between 1 and {MAX_GRAPH_NODES}")

    root = _resolve_root(snapshot, symbol)
    symbols = {item.logical_key: item for item in snapshot.code_symbols}
    adjacency: dict[str, list[CodeDependency]] = defaultdict(list)
    unresolved: dict[str, list[CodeDependency]] = defaultdict(list)
    for dependency in snapshot.code_dependencies:
        if dependency.target_symbol_key is None:
            unresolved[dependency.source_symbol_key].append(dependency)
            continue
        adjacency[dependency.source_symbol_key].append(dependency)
        adjacency[dependency.target_symbol_key].append(dependency)
    for values in adjacency.values():
        values.sort(key=lambda item: item.logical_key)
    for values in unresolved.values():
        values.sort(key=lambda item: item.logical_key)

    queue: deque[tuple[str, int]] = deque([(root.logical_key, 0)])
    selected_keys: list[str] = [root.logical_key]
    selected_set = {root.logical_key}
    selected_dependencies: dict[str, CodeDependency] = {}
    selected_unresolved: dict[str, CodeDependency] = {}
    truncated = False

    while queue:
        current_key, depth = queue.popleft()
        for dependency in unresolved.get(current_key, []):
            selected_unresolved[dependency.logical_key] = dependency
        neighbors = adjacency.get(current_key, [])
        if depth >= max_depth:
            if any(
                (
                    dependency.target_symbol_key
                    if dependency.source_symbol_key == current_key
                    else dependency.source_symbol_key
                )
                not in selected_set
                for dependency in neighbors
            ):
                truncated = True
            continue
        for dependency in neighbors:
            target_key = dependency.target_symbol_key
            if target_key is None:
                continue
            neighbor = (
                target_key
                if dependency.source_symbol_key == current_key
                else dependency.source_symbol_key
            )
            if neighbor not in symbols:
                raise ValueError("resolved dependency target is missing from the validated graph")
            if neighbor not in selected_set:
                if len(selected_keys) >= max_nodes:
                    truncated = True
                    continue
                selected_set.add(neighbor)
                selected_keys.append(neighbor)
                queue.append((neighbor, depth + 1))
            selected_dependencies[dependency.logical_key] = dependency

    evidence = {item.id: item for item in snapshot.evidence}
    citation_lines: dict[tuple[UUID, int, int], Citation] = {}
    for node in (symbols[key] for key in selected_keys):
        source = evidence[node.evidence_id]
        locator = source.locator.model_copy(
            update={"line_start": node.line_start, "line_end": node.line_end}
        )
        citation_lines[(node.evidence_id, node.line_start, node.line_end)] = Citation(
            evidence_id=node.evidence_id,
            locator=locator,
        )
    for dependency in (*selected_dependencies.values(), *selected_unresolved.values()):
        source = evidence[dependency.evidence_id]
        locator = source.locator.model_copy(
            update={
                "line_start": dependency.line_start,
                "line_end": dependency.line_end,
            }
        )
        citation_lines[
            (dependency.evidence_id, dependency.line_start, dependency.line_end)
        ] = Citation(evidence_id=dependency.evidence_id, locator=locator)

    return CodeGraphTrace(
        root=root,
        nodes=tuple(symbols[key] for key in selected_keys),
        dependencies=tuple(selected_dependencies.values()),
        unresolved_dependencies=tuple(selected_unresolved.values()),
        citations=tuple(
            citation_lines[key]
            for key in sorted(citation_lines, key=lambda value: (str(value[0]), value[1], value[2]))
        ),
        max_depth=max_depth,
        max_nodes=max_nodes,
        truncated=truncated,
    )
